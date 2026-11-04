import { Body1, Field, Input, Link, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  hint: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
  },
  links: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalM,
  },
});

export type HuggingFaceTokenFieldProps = {
  value: string;
  onChange: (value: string) => void;
  /** The gated checkpoint's `org/repo` id, used to link straight to its access-request page. */
  huggingFaceRepoId?: string;
  disabled?: boolean;
};

/**
 * Hugging Face token input with inline links to the two things a presenter actually needs to get
 * unblocked without leaving the flow: creating a read-scoped token, and (for gated checkpoints)
 * requesting access to that specific repo. The token itself is never persisted here or by the
 * backend (FR-011) — it is used transiently for the deployment request and cleared immediately.
 */
export default function HuggingFaceTokenField({
  value,
  onChange,
  huggingFaceRepoId,
  disabled,
}: HuggingFaceTokenFieldProps) {
  const styles = useStyles();

  return (
    <Field
      label="Hugging Face token"
      hint={
        <span className={styles.hint}>
          <Body1>The token is used transiently for this request and cleared immediately.</Body1>
          <span className={styles.links}>
            <Link href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">
              Create a token (read access) ↗
            </Link>
            {huggingFaceRepoId ? (
              <Link
                href={`https://huggingface.co/${huggingFaceRepoId}`}
                target="_blank"
                rel="noreferrer"
              >
                Request access to {huggingFaceRepoId} ↗
              </Link>
            ) : null}
          </span>
        </span>
      }
    >
      <Input
        aria-label="Hugging Face token"
        type="password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="hf_..."
        disabled={disabled}
      />
    </Field>
  );
}
