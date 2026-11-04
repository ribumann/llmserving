import { apiRequest } from './apiClient';
import type { ComparisonResponse, CreateComparisonRequest } from './types';

export function createComparison(payload: CreateComparisonRequest) {
  return apiRequest<ComparisonResponse>('/comparisons', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getComparison(comparisonId: string) {
  return apiRequest<ComparisonResponse>(`/comparisons/${comparisonId}`);
}
