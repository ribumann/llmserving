import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Body1,
  Button,
  Field,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ApiError } from '../services/apiClient';
import { createComparison, getComparison } from '../services/comparisonsApi';
import type { ComparisonResponse } from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  LoadingState,
  PageHeader,
  RouterLink,
  SectionCard,
  StatusBadge,
  StatusMessage,
  formatStateLabel,
  statusTone,
} from '../components/kit';

const useStyles = makeStyles({
  stack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalL,
  },
  formStack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
  },
  reportRow: {
    display: 'grid',
    gap: tokens.spacingHorizontalS,
    gridTemplateColumns: 'minmax(0, 1fr) auto',
    alignItems: 'end',
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  list: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
  },
  preformatted: {
    whiteSpace: 'pre-wrap',
    fontFamily: tokens.fontFamilyMonospace,
  },
});

function formatValue(value: unknown) {
  if (value === null || value === undefined) {
    return 'n/a';
  }

  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  return JSON.stringify(value, null, 2);
}

function getComparisonErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    return error.message;
  }

  return error instanceof Error ? error.message : 'Comparison request failed.';
}

export default function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [comparison, setComparison] = useState<ComparisonResponse>();
  const [reportIds, setReportIds] = useState(['', '']);
  const [title, setTitle] = useState('');
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [creatingComparison, setCreatingComparison] = useState(false);
  const [error, setError] = useState<string>();

  const comparisonId = searchParams.get('comparisonId')?.trim() ?? '';
  const trimmedReportIds = useMemo(
    () => reportIds.map((reportId) => reportId.trim()).filter(Boolean),
    [reportIds],
  );
  const canCompare = trimmedReportIds.length >= 2 && !creatingComparison;

  useEffect(() => {
    if (!comparisonId) {
      setComparison(undefined);
      setLoadingComparison(false);
      return;
    }

    let active = true;

    async function loadComparison() {
      setLoadingComparison(true);
      setError(undefined);

      try {
        const response = await getComparison(comparisonId);

        if (active) {
          setComparison(response);
        }
      } catch (nextError) {
        if (active) {
          setComparison(undefined);
          setError(getComparisonErrorMessage(nextError));
        }
      } finally {
        if (active) {
          setLoadingComparison(false);
        }
      }
    }

    void loadComparison();

    return () => {
      active = false;
    };
  }, [comparisonId]);

  function updateReportId(index: number, value: string) {
    setReportIds((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));
  }

  function addReportRow() {
    setReportIds((current) => [...current, '']);
  }

  function removeReportRow(index: number) {
    setReportIds((current) => {
      if (current.length <= 2) {
        return current;
      }

      return current.filter((_, itemIndex) => itemIndex !== index);
    });
  }

  async function handleCompare() {
    if (trimmedReportIds.length < 2) {
      setError('Enter at least two report ids before creating a comparison.');
      return;
    }

    setCreatingComparison(true);
    setError(undefined);

    try {
      const response = await createComparison({
        reportIds: trimmedReportIds,
        title: title.trim() || undefined,
      });

      setComparison(response);
      setSearchParams({ comparisonId: response.comparisonId });
    } catch (nextError) {
      setError(getComparisonErrorMessage(nextError));
    } finally {
      setCreatingComparison(false);
    }
  }

  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Evaluate"
        title="Compare reports"
        description="Compare quality and performance evidence side by side across runs."
      />

      <SectionCard
        title="1. Choose result report IDs"
      >
        <div className={styles.formStack}>
          <Body1>
            Copy the Result report ID from two or more completed reports in{' '}
            <RouterLink to="/quality/run">Quality Run</RouterLink> or{' '}
            <RouterLink to="/performance/run">Performance Run</RouterLink>. Bookmark or share the
            generated <code>?comparisonId=</code> URL to reopen the comparison.
          </Body1>

          <Field label="Optional comparison title">
            <Input
              aria-label="Comparison title"
              placeholder="July regression check"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>

          {reportIds.map((reportId, index) => (
            <div className={styles.reportRow} key={`report-id-${index}`}>
              <Field label={`Result report ID ${index + 1}`}>
                <Input
                  aria-label={`Result report ID ${index + 1}`}
                  placeholder="report_abc123"
                  value={reportId}
                  onChange={(event) => updateReportId(index, event.target.value)}
                />
              </Field>
              <Button onClick={() => removeReportRow(index)} disabled={reportIds.length <= 2}>
                Remove
              </Button>
            </div>
          ))}
        </div>

        {error ? <StatusMessage intent="error">{error}</StatusMessage> : null}
        <div className={styles.actions}>
          <Button onClick={addReportRow}>Add report</Button>
          <Button appearance="primary" onClick={() => void handleCompare()} disabled={!canCompare}>
            {creatingComparison ? 'Creating comparison…' : 'Compare'}
          </Button>
        </div>
      </SectionCard>

      {loadingComparison ? <LoadingState label="Loading comparison…" /> : null}

      {comparison ? (
        <>
          <SectionCard title="2. Comparison result">
            <InfoGrid>
              <InfoPanel title="Comparison metadata">
                <DataList
                  items={[
                    { label: 'Comparison id', value: comparison.comparisonId },
                    {
                      label: 'Comparability status',
                      value: (
                        <StatusBadge tone={statusTone(comparison.comparabilityStatus)}>
                          {formatStateLabel(comparison.comparabilityStatus)}
                        </StatusBadge>
                      ),
                    },
                    { label: 'Reports compared', value: comparison.reports.length },
                  ]}
                />
              </InfoPanel>
            </InfoGrid>

            {comparison.comparabilityStatus === 'not-directly-comparable' ? (
              <StatusMessage intent="warning" title="Not directly comparable">
                <ul className={styles.list}>
                  {comparison.reasons.map((reason) => (
                    <li key={reason}>
                      <Body1>{reason}</Body1>
                    </li>
                  ))}
                </ul>
              </StatusMessage>
            ) : (
              <StatusMessage intent="success">
                The backend marked these reports as comparable, so you can interpret the section
                deltas directly.
              </StatusMessage>
            )}

            <Table aria-label="Compared reports" size="small">
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>Result report ID</TableHeaderCell>
                  <TableHeaderCell>Revision id</TableHeaderCell>
                  <TableHeaderCell>Environment id</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparison.reports.map((report) => (
                  <TableRow key={report.reportId}>
                    <TableCell>{report.reportId}</TableCell>
                    <TableCell>{report.revisionId ?? 'n/a'}</TableCell>
                    <TableCell>{report.environmentId ?? 'n/a'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>

          {comparison.sections.map((section, sectionIndex) => (
            <SectionCard key={`${section.title}-${sectionIndex}`} title={`${sectionIndex + 3}. ${section.title}`}>
              {section.items.length ? (
                <InfoGrid>
                  {section.items.map((item, itemIndex) => (
                    <InfoPanel key={`${section.title}-item-${itemIndex}`} title={`Item ${itemIndex + 1}`}>
                      <DataList
                        items={Object.entries(item).map(([key, value]) => ({
                          label: formatStateLabel(key),
                          value:
                            typeof value === 'string' ||
                            typeof value === 'number' ||
                            typeof value === 'boolean' ||
                            value === null ||
                            value === undefined ? (
                              formatValue(value)
                            ) : (
                              <span className={styles.preformatted}>{formatValue(value)}</span>
                            ),
                        }))}
                      />
                    </InfoPanel>
                  ))}
                </InfoGrid>
              ) : (
                <EmptyState title="No items in this section">
                  The comparison finished successfully, but this section returned no row-level data.
                </EmptyState>
              )}
            </SectionCard>
          ))}
        </>
      ) : !loadingComparison && comparisonId ? (
        <EmptyState title="No comparison loaded">
          The requested comparison id could not be loaded. Check the URL or create a new comparison.
        </EmptyState>
      ) : null}
    </div>
  );
}
