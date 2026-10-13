import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type SyntheticEvent } from "react";
import { Button, Field, Input, Notice, Pill } from "../../components/ui";
import { ApiError, api, call, errorMessage, type Schemas } from "../../lib/api/client";
import { fmtDateTime } from "../../lib/format";
import { RULE_BOUNDS, validateThreshold } from "./ruleValidation";

type Rule = Schemas["RuleOut"];

export function RuleEditor({ rule, canEdit }: { rule: Rule; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [threshold, setThreshold] = useState(rule.threshold);
  const [enabled, setEnabled] = useState(rule.enabled);
  const [touched, setTouched] = useState(false);
  const [baseVersion, setBaseVersion] = useState(rule.version);
  const [editing, setEditing] = useState(false);
  const [seenVersion, setSeenVersion] = useState(rule.version);
  // A background refetch brought a newer rule. Adopt it unless the user is mid-edit; in that case
  // keep their input and the version they started from so saving surfaces a 409 conflict instead
  // of silently discarding their change or overwriting the newer one.
  if (rule.version !== seenVersion) {
    setSeenVersion(rule.version);
    if (!editing) {
      setThreshold(rule.threshold);
      setEnabled(rule.enabled);
      setBaseVersion(rule.version);
    }
  }
  const bounds = RULE_BOUNDS[rule.rule_type];
  const clientError = touched ? validateThreshold(rule.rule_type, threshold) : null;
  const dirty = editing && (threshold !== rule.threshold || enabled !== rule.enabled || baseVersion !== rule.version);

  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH("/api/v1/rules/{rule_id}", {
          params: { path: { rule_id: rule.id } },
          body: { version: baseVersion, threshold: threshold !== rule.threshold ? threshold : null, enabled: enabled !== rule.enabled ? enabled : null },
        }),
      ),
    onSuccess: async (updated) => {
      setEditing(false);
      setBaseVersion(updated.version);
      setThreshold(updated.threshold);
      setEnabled(updated.enabled);
      setTouched(false);
      await queryClient.invalidateQueries({ queryKey: ["instrument", rule.instrument_id] });
    },
  });

  const conflict = save.error instanceof ApiError && save.error.code === "VERSION_CONFLICT" ? save.error : null;
  const serverFieldError = save.error instanceof ApiError && save.error.status === 422 ? save.error.message : undefined;

  async function reload() {
    await queryClient.invalidateQueries({ queryKey: ["instrument", rule.instrument_id] });
    const fresh = queryClient.getQueryData<Schemas["InstrumentDetail"]>(["instrument", rule.instrument_id])?.rules.find((r) => r.id === rule.id);
    if (fresh) {
      setThreshold(fresh.threshold);
      setEnabled(fresh.enabled);
      setBaseVersion(fresh.version);
    }
    setEditing(false);
    setTouched(false);
    save.reset();
  }

  function onSubmit(e: SyntheticEvent) {
    e.preventDefault();
    setTouched(true);
    if (validateThreshold(rule.rule_type, threshold)) return;
    save.mutate();
  }

  const label = rule.rule_type === "STALE" ? "Stale quote" : "Wide spread";
  return (
    <form onSubmit={onSubmit} className="space-y-2 rounded-md border border-slate-200 p-3" aria-label={`${label} rule`} noValidate>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">
          {label} rule <span className="font-normal text-slate-500">v{baseVersion}</span>
        </p>
        <Pill tone={rule.enabled ? "good" : "neutral"}>{rule.enabled ? "Enabled" : "Disabled"}</Pill>
      </div>
      <p className="text-xs text-slate-500">
        {rule.rule_type === "STALE"
          ? "Opens an incident when no quote has been received by the backend for longer than the threshold."
          : "Opens an incident when the bid/ask spread is strictly greater than the threshold."}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={`Threshold (${bounds.unitLabel})`} error={clientError ?? serverFieldError} hint={`${bounds.min}–${bounds.max} ${bounds.unitLabel}`}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              inputMode="decimal"
              value={threshold}
              disabled={!canEdit}
              onChange={(e) => {
                setThreshold(e.target.value);
                setTouched(true);
                setEditing(true);
              }}
              className="w-32 font-mono"
            />
          )}
        </Field>
        <label className="flex items-center gap-2 pb-6 text-sm">
          <input type="checkbox" checked={enabled} disabled={!canEdit} onChange={(e) => {
              setEnabled(e.target.checked);
              setEditing(true);
            }} className="h-4 w-4 accent-teal-700" />
          Enabled
        </label>
        {canEdit ? (
          <div className="flex gap-2 pb-6">
            <Button type="submit" variant="primary" busy={save.isPending} disabled={!dirty}>
              Save rule
            </Button>
          </div>
        ) : null}
      </div>
      {!canEdit ? <p className="text-xs text-slate-500">Viewers can read rules; operators can change them.</p> : null}
      {conflict ? (
        <Notice tone="warn">
          <p className="font-semibold">Someone else changed this rule.</p>
          <p>{conflict.message}</p>
          <Button className="mt-2" onClick={() => void reload()}>
            Reload latest rule
          </Button>
        </Notice>
      ) : save.isError && !serverFieldError ? (
        <Notice tone="bad">{errorMessage(save.error)}</Notice>
      ) : null}
      {save.isSuccess ? <Notice tone="good">Saved. New rule version v{save.data.version}; the evaluator applies it within seconds.</Notice> : null}
      <p className="text-[11px] text-slate-400">Last updated {fmtDateTime(rule.updated_at)}</p>
    </form>
  );
}
