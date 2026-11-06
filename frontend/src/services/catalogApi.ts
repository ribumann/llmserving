import { apiRequest } from './apiClient';
import type { CloudDeploymentProfile, ModelCatalogEntry, RequestIdEnvelope } from './types';

export interface ListProfilesResponse extends RequestIdEnvelope {
  profiles: CloudDeploymentProfile[];
}

export interface ListCatalogResponse extends RequestIdEnvelope {
  entries: ModelCatalogEntry[];
}

type BackendProfile = RequestIdEnvelope & {
  profiles: Array<{
    profileId: string;
    provider: 'azure' | 'local';
    modelSizeClass: '3b' | '7b' | '70b';
    eligibleRegions: string[];
    vmSku: string;
    capacityAssumptions: Record<string, unknown>;
    configurableInputs: Record<string, unknown>;
    knownLimitations: string[];
  }>;
};

type BackendCatalog = RequestIdEnvelope & {
  catalog?: Array<{
    catalogEntryId: string;
    family: string;
    sizeClass: '3b' | '7b' | '70b';
    huggingFaceRepoId: string;
    checkpointRef: string;
    isGated: boolean;
    license: string;
    compatibleProfileIds: string[];
    notes: string;
  }>;
  entries?: Array<{
    catalogEntryId: string;
    family: string;
    sizeClass: '3b' | '7b' | '70b';
    huggingFaceRepoId: string;
    checkpointRef: string;
    isGated: boolean;
    license: string;
    compatibleProfileIds: string[];
    notes: string;
  }>;
};

function toSizeClass(value: '3b' | '7b' | '70b'): 'small' | 'medium' | 'large' {
  if (value === '7b') {
    return 'medium';
  }
  if (value === '70b') {
    return 'large';
  }
  return 'small';
}

function inferInputType(value: unknown): 'string' | 'number' | 'boolean' | 'enum' {
  if (typeof value === 'number') {
    return 'number';
  }
  if (typeof value === 'boolean') {
    return 'boolean';
  }
  return 'string';
}

export async function listProfiles(): Promise<ListProfilesResponse> {
  const response = await apiRequest<BackendProfile>('/profiles');
  return {
    requestId: response.requestId,
    profiles: response.profiles.map((profile) => ({
      id: profile.profileId,
      name: profile.provider === 'local' ? 'Local (Ollama)' : profile.profileId,
      provider: profile.provider,
      sizeClass: toSizeClass(profile.modelSizeClass),
      description:
        profile.provider === 'local'
          ? 'Run the demo narrative against a local Ollama runtime with no Azure access.'
          : `Azure profile targeting ${profile.vmSku}.`,
      expectedModelClass: profile.modelSizeClass,
      regions:
        profile.profileId === 'azure-single-gpu-3b'
          ? Array.from(new Set([...profile.eligibleRegions, 'italynorth']))
          : profile.eligibleRegions,
      resourceAssumptions:
        profile.provider === 'local'
          ? ['Presenter-managed hardware', 'Ollama installed and running locally']
          : [profile.vmSku],
      capacityRequirements: profile.knownLimitations,
      configurableInputs: [
        ...Object.entries(profile.configurableInputs)
          .filter(
            ([name, value]) =>
              ['string', 'number', 'boolean'].includes(typeof value) &&
              (profile.provider !== 'azure' || !['vmSizeOverride', 'vmPriority'].includes(name)),
          )
          .map(([name, value]) => ({
            name,
            type: inferInputType(value),
            required: false,
            defaultValue: value as string | number | boolean,
          })),
        ...(profile.provider === 'azure'
          ? [
              {
                name: 'vmSizeOverride',
                type: 'string' as const,
                required: false,
                defaultValue:
                  typeof profile.configurableInputs.vmSizeOverride === 'string'
                    ? profile.configurableInputs.vmSizeOverride
                    : '',
                description: 'Optional Azure VM SKU override; leave empty to use the profile size class.',
              },
              {
                name: 'vmPriority',
                type: 'enum' as const,
                required: true,
                defaultValue:
                  typeof profile.configurableInputs.vmPriority === 'string'
                    ? profile.configurableInputs.vmPriority
                    : 'Spot',
                options: ['Spot', 'Regular'],
              },
            ]
          : []),
      ],
      knownLimitations: profile.knownLimitations,
    })),
  };
}

export async function listCatalog(): Promise<ListCatalogResponse> {
  const response = await apiRequest<BackendCatalog>('/catalog');
  const entries = response.entries ?? response.catalog ?? [];
  return {
    requestId: response.requestId,
    entries: entries.map((entry) => ({
      id: entry.catalogEntryId,
      family: entry.family,
      sizeClass: toSizeClass(entry.sizeClass),
      huggingFaceRepo: entry.huggingFaceRepoId,
      checkpoint: entry.checkpointRef,
      license: entry.license,
      gated: entry.isGated,
      languageCoverage: [],
      compatibleProfileIds: entry.compatibleProfileIds,
      demonstrationValue: entry.notes,
      evaluationLimitations: [],
    })),
  };
}
