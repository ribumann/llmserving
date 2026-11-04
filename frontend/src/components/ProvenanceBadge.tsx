import type {
  GoldenDatasetProvenance,
  GoldenDatasetReviewStatus,
} from '../services/types';
import { StatusBadge, type StatusTone } from './kit';

type ProvenanceBadgeProps = {
  provenance: GoldenDatasetProvenance;
  reviewStatus: GoldenDatasetReviewStatus;
};

function getBadgeCopy(
  provenance: GoldenDatasetProvenance,
  reviewStatus: GoldenDatasetReviewStatus,
): { label: string; tone: StatusTone } {
  if (provenance === 'curated') {
    return {
      label: reviewStatus === 'unreviewed' ? 'Curated · Unreviewed' : 'Curated',
      tone: reviewStatus === 'unreviewed' ? 'warning' : 'brand',
    };
  }

  return {
    label: `AI-generated · ${reviewStatus === 'reviewed' ? 'Reviewed' : 'Unreviewed'}`,
    tone: reviewStatus === 'reviewed' ? 'success' : 'warning',
  };
}

export default function ProvenanceBadge({ provenance, reviewStatus }: ProvenanceBadgeProps) {
  const badge = getBadgeCopy(provenance, reviewStatus);

  return <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>;
}
