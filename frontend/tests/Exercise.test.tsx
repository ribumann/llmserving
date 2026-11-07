import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ExercisePage from '../src/pages/Exercise';
import { ApiError } from '../src/services/apiClient';
import { submitPrompt } from '../src/services/deploymentsApi';
import { getEnvironment, listEnvironments } from '../src/services/environmentsApi';

vi.mock('../src/services/deploymentsApi', () => ({
  submitPrompt: vi.fn(),
}));

vi.mock('../src/services/environmentsApi', () => ({
  getEnvironment: vi.fn(),
  listEnvironments: vi.fn(),
}));

const mockedSubmitPrompt = vi.mocked(submitPrompt);
const mockedGetEnvironment = vi.mocked(getEnvironment);
const mockedListEnvironments = vi.mocked(listEnvironments);

describe('ExercisePage', () => {
  beforeEach(() => {
    mockedGetEnvironment.mockResolvedValue({
      environmentId: 'env-123',
      name: 'demo-ready',
      provider: 'azure',
      profileId: 'azure-single-gpu-7b',
      region: 'southcentralus',
      state: 'ready',
      activeOperationId: null,
      activeDeploymentRevisionId: 'rev-001',
      resources: [],
      updatedAt: '2026-08-19T09:45:00Z',
    });

    mockedListEnvironments.mockResolvedValue({
      requestId: 'req-environments',
      environments: [
        {
          environmentId: 'env-123',
          profileId: 'azure-single-gpu-7b',
          provider: 'azure',
          region: 'southcentralus',
          lifecycleState: 'ready',
          activeOperationId: null,
        },
      ],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    { ttftMs: 220, interTokenLatencyMsAvg: 18, totalLatencyMs: 945, displayed: ['220 ms', '18 ms', '945 ms'] },
    { ttftMs: 220.123456, interTokenLatencyMsAvg: 18.987654, totalLatencyMs: 945.456789, displayed: ['220.1 ms', '19.0 ms', '945.5 ms'] },
  ])('renders display-only timing precision and revision trace for $ttftMs ms TTFT', async ({ displayed, ...timing }) => {
    const user = userEvent.setup();

    mockedSubmitPrompt.mockResolvedValue({
      requestId: 'req-prompt',
      deploymentRevisionId: 'rev-001',
      responseText: 'South Central US has healthier GPU capacity and a ready serving revision.',
      timing,
      activeRevision: {
        deploymentRevisionId: 'rev-001',
        modelConfigId: 'model-config-001',
        inferenceConfigId: 'inference-config-001',
      },
    });

    const { unmount } = render(
      <MemoryRouter initialEntries={['/exercise?environmentId=env-123']}>
        <ExercisePage />
      </MemoryRouter>,
    );

    // The environment auto-loads from the ?environmentId= deep link on mount.
    await waitFor(() => {
      expect(mockedGetEnvironment).toHaveBeenCalledWith('env-123');
    });

    await user.type(screen.getByRole('textbox', { name: /prompt/i }), 'Why is this region preferred?');
    await user.click(screen.getByRole('button', { name: /submit prompt/i }));

    await waitFor(() => {
      expect(mockedSubmitPrompt).toHaveBeenCalledWith('env-123', {
        prompt: 'Why is this region preferred?',
        parameters: {
          temperature: 0.2,
        },
      });
    });

    expect(
      await screen.findByText(/south central us has healthier gpu capacity/i),
    ).toBeInTheDocument();
    displayed.forEach((value) => expect(screen.getByText(value)).toBeInTheDocument());
    expect((await mockedSubmitPrompt.mock.results[0].value).timing).toEqual(timing);
    expect(screen.getAllByText(/rev-001/i)).toHaveLength(2);
    expect(
      screen.getAllByText('Prompts are not saved. Closing or refreshing this page clears the session history.'),
    ).toHaveLength(1);
    expect(screen.queryByText('Retention note')).not.toBeInTheDocument();

    unmount();
    render(
      <MemoryRouter initialEntries={['/exercise?environmentId=env-123']}>
        <ExercisePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /reload environment/i })).toBeEnabled();
    });
    expect(screen.getByText('No prompts submitted in this browser session yet')).toBeInTheDocument();
    expect(screen.queryByText(/south central us has healthier gpu capacity/i)).not.toBeInTheDocument();
  });

  it('maps no-ready-deployment to a deploy-focused error message', async () => {
    const user = userEvent.setup();

    mockedSubmitPrompt.mockRejectedValue(
      new ApiError('No deployment is ready.', {
        requestId: 'req-error',
        error: {
          code: 'no_ready_deployment',
          message: 'No deployment is ready.',
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={['/exercise?environmentId=env-123']}>
        <ExercisePage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockedGetEnvironment).toHaveBeenCalled();
    });

    await user.type(screen.getByRole('textbox', { name: /prompt/i }), 'Hello');
    await user.click(screen.getByRole('button', { name: /submit prompt/i }));

    expect(
      await screen.findByText(/open deploy to activate one before retrying/i),
    ).toBeInTheDocument();
  });
});
