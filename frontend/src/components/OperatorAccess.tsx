import { Button, Link } from '@fluentui/react-components';
import { useLocation } from 'react-router-dom';
import { EmptyState, LoadingState, PageHeader, RouterLink } from './kit';
import type { OperatorSession } from '../services/useOperatorSession';

const WORKFLOW = [
  [
    '/provision',
    'Provision',
    'Choose a deployment profile, review quota and capacity, and create an environment.',
  ],
  [
    '/deploy',
    'Deploy',
    'Select a model and inference configuration for a provisioned environment.',
  ],
  [
    '/exercise',
    'Exercise',
    'Send prompts to a deployed model and inspect its responses.',
  ],
  [
    '/retune',
    'Retune',
    'Version model and inference settings, then redeploy the configuration.',
  ],
  [
    '/quality',
    'Quality',
    'Run golden datasets and benchmarks, then review quality reports.',
  ],
  [
    '/performance',
    'Performance',
    'Measure serving performance with a configured workload and review the report.',
  ],
  [
    '/compare',
    'Compare',
    'Compare recorded runs with their configuration and provenance.',
  ],
  [
    '/history',
    'Experiment History',
    'Browse recorded experiments and open their reports.',
  ],
  [
    '/environments',
    'Environment detail',
    'Inspect environment state, deployments, configuration and run history.',
  ],
  [
    '/teardown',
    'Teardown',
    'Review the teardown plan before removing an environment and its resources.',
  ],
] as const;

export function SignInLink() {
  const { pathname, search } = useLocation();
  const target = encodeURIComponent(`${pathname}${search}`);
  return (
    <Link href={`/.auth/login/aad?post_login_redirect_uri=${target}`}>
      Sign in with Microsoft
    </Link>
  );
}

export function OperatorAccess({
  session,
  retry,
}: {
  session: OperatorSession;
  retry: () => void;
}) {
  const { pathname } = useLocation();
  const step = WORKFLOW.find(([prefix]) => pathname.startsWith(prefix));
  return (
    <section>
      <PageHeader
        title={step?.[1] ?? 'Operator workspace'}
        description={step?.[2]}
      />
      {session === 'checking' ? (
        <LoadingState label="Checking operator access..." />
      ) : (
        <EmptyState
          title={
            session === 'forbidden'
              ? 'This account does not have operator access'
              : session === 'unavailable'
                ? 'Operator access could not be verified'
                : 'Sign in to use the operator workspace'
          }
          actions={
            <>
              {session === 'unavailable' ? (
                <Button onClick={retry}>Check access again</Button>
              ) : (
                <SignInLink />
              )}
              <RouterLink to="/">Explore the overview</RouterLink>
            </>
          }
        >
          {session === 'unavailable'
            ? 'The authentication service is unavailable or not configured. Live data and actions remain locked until access can be verified.'
            : session === 'forbidden'
              ? 'Use an account approved for this deployment. Signing in does not grant access to an unapproved account.'
              : 'The public UI explains the workflow. Live configuration, environments, history and reports are private. Provisioning, deployment, prompts, evaluations, retuning and teardown require an authorized account.'}
        </EmptyState>
      )}
    </section>
  );
}
