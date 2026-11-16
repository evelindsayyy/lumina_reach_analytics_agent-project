import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { CfnOutput, Duration, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as fs from 'fs';
import * as path from 'path';

/**
 * What `agent-app ac-gen` writes to agentcore/app-config.json for this stack: the names that
 * are not in agentcore.json's schema. Never edited by hand.
 */
export interface AppConfig {
  agentRuntimeName: string;
  mcpRuntimeName: string;
  /** The SSM SecureString holding the Snowflake service user's private key. */
  snowflakeKeyParamName: string;
  /** The Cognito managed login domain: https://<prefix>.auth.<region>.amazoncognito.com */
  cognitoDomainPrefix: string;
  /** Where the web app may send users back after sign-in and sign-out. */
  callbackUrls: string[];
  logoutUrls: string[];
}

/** agentcore/app-config.json, found by walking up from this file to the folder of agentcore.json. */
export function readAppConfig(start: string = __dirname): AppConfig {
  let dir = start;
  while (!fs.existsSync(path.join(dir, 'agentcore.json'))) {
    const parent = path.dirname(dir);
    if (parent === dir) {
      throw new Error('agentcore/app-config.json not found: run `mise run ac-gen` first');
    }
    dir = parent;
  }
  return JSON.parse(fs.readFileSync(path.join(dir, 'app-config.json'), 'utf-8')) as AppConfig;
}

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
  appConfig?: AppConfig;
}

/**
 * The whole deployment of the analytics agent:
 *
 * - AnalyticsMcp: the data tools. AWS_IAM (SigV4) inbound, and only the agent's role may invoke
 *   it. Its role alone reads the Snowflake key, and it is denied every Bedrock model call.
 * - AnalyticsAgent: the agent. CUSTOM_JWT inbound: AgentCore verifies the Cognito access token
 *   before a request arrives, and forwards Authorization so the agent can read the user's sub.
 * - Cognito: the user pool the web app signs users in with (managed login, code + PKCE).
 * - DynamoDB: the quota table, read and written by the agent only.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    const spec = props.application.spec;
    // An empty project (the teardown, `mise run ac-down`) declares no runtime and must still synthesize.
    if (!spec.runtimes?.length) {
      this.application = new AgentCoreApplication(this, 'Application', props.application);
      return;
    }
    const cfg = props.appConfig ?? readAppConfig();

    // --- Cognito: who may call the agent ---
    const userPool = new cognito.UserPool(this, 'UserPool', {
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      passwordPolicy: { minLength: 12, requireSymbols: false },
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const domain = userPool.addDomain('Domain', {
      cognitoDomain: { domainPrefix: cfg.cognitoDomainPrefix },
      managedLoginVersion: cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN,
    });
    const webClient = userPool.addClient('WebClient', {
      // A browser app holds no secret: authorization code with PKCE.
      generateSecret: false,
      authFlows: { userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        callbackUrls: cfg.callbackUrls,
        logoutUrls: cfg.logoutUrls,
      },
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(30),
      preventUserExistenceErrors: true,
    });
    new cognito.CfnManagedLoginBranding(this, 'LoginBranding', {
      userPoolId: userPool.userPoolId,
      clientId: webClient.userPoolClientId,
      useCognitoProvidedValues: true,
    });

    // --- The agent's inbound auth: the user pool's access tokens, from the web client only ---
    const discoveryUrl =
      `https://cognito-idp.${this.region}.amazonaws.com/${userPool.userPoolId}/.well-known/openid-configuration`;
    const application: AgentCoreApplicationProps = {
      ...props.application,
      spec: {
        ...spec,
        runtimes: spec.runtimes.map((runtime) =>
          runtime.name === cfg.agentRuntimeName
            ? {
                ...runtime,
                authorizerType: 'CUSTOM_JWT' as const,
                authorizerConfiguration: {
                  customJwtAuthorizer: { discoveryUrl, allowedClients: [webClient.userPoolClientId] },
                },
                // forwarded only because it is listed: the agent reads the user's sub from it
                requestHeaderAllowlist: ['Authorization'],
              }
            : runtime,
        ),
      },
    };
    this.application = new AgentCoreApplication(this, 'Application', application);
    const agent = this.application.runtime(cfg.agentRuntimeName);
    const mcp = this.application.runtime(cfg.mcpRuntimeName);

    // --- The agent may call the MCP server, signed with SigV4 ---
    // bind() grants the agent's role bedrock-agentcore:InvokeAgentRuntime on this one runtime and
    // sets AGENTCORE_RUNTIME_ANALYTICSMCP_ARN on the agent. No other principal is granted it.
    mcp.bind(agent);

    // --- Only the MCP runtime reads the warehouse key ---
    const keyParamArn = `arn:${this.partition}:ssm:${this.region}:${this.account}:parameter${cfg.snowflakeKeyParamName}`;
    mcp.grant(['ssm:GetParameter'], [keyParamArn]);
    // The MCP server runs SQL and calls no model; the construct grants every runtime Bedrock
    // invoke by default, so take it back from this one explicitly.
    mcp.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.DENY,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
          'bedrock:Converse',
          'bedrock:ConverseStream',
          'bedrock:CountTokens',
        ],
        resources: ['*'],
      }),
    );
    // And the agent never reads it, even if a later grant would allow it.
    agent.addToRolePolicy(
      new iam.PolicyStatement({ effect: iam.Effect.DENY, actions: ['ssm:GetParameter*'], resources: [keyParamArn] }),
    );

    // --- The monthly quota: deployment-wide and per user, written by the agent only ---
    const quotaTable = new dynamodb.Table(this, 'QuotaTable', {
      partitionKey: { name: 'app_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    quotaTable.grantReadWriteData(agent);
    agent.addEnvironmentVariable('DYNAMODB_TABLE_NAME_QUOTA', quotaTable.tableName);

    // --- What the web app needs (none of it secret) ---
    new CfnOutput(this, 'AgentRuntimeArn', { value: agent.runtimeArn });
    new CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new CfnOutput(this, 'WebClientId', { value: webClient.userPoolClientId });
    new CfnOutput(this, 'CognitoDomain', { value: domain.baseUrl() });
  }
}
