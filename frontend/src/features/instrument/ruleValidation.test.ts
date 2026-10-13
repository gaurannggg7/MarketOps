import { describe, expect, it } from "vitest";
import { RULE_BOUNDS, validateThreshold } from "./ruleValidation";

describe("validateThreshold", () => {
  it.each(["", "   "])("rejects blank input %j", (raw) => {
    expect(validateThreshold("STALE", raw)).toBe("Enter a threshold.");
    expect(validateThreshold("WIDE_SPREAD", raw)).toBe("Enter a threshold.");
  });

  it.each(["abc", "-5", "1e3", "1,5", "--1", "5 s", ".5", "5."])("rejects non-numeric or negative input %j", (raw) => {
    expect(validateThreshold("STALE", raw)).toBe("Enter a positive number of seconds.");
    expect(validateThreshold("WIDE_SPREAD", raw)).toBe("Enter a positive number of basis points.");
  });

  it.each([
    ["STALE", "0", "Threshold must be between 1 and 3600 seconds."],
    ["STALE", "0.99", "Threshold must be between 1 and 3600 seconds."],
    ["STALE", "3601", "Threshold must be between 1 and 3600 seconds."],
    ["WIDE_SPREAD", "0.49", "Threshold must be between 0.5 and 5000 basis points."],
    ["WIDE_SPREAD", "5000.01", "Threshold must be between 0.5 and 5000 basis points."],
  ] as const)("%s %s is out of bounds", (type, raw, message) => {
    expect(validateThreshold(type, raw)).toBe(message);
  });

  it.each([
    ["STALE", "1.234"],
    ["STALE", "30.001"],
    ["WIDE_SPREAD", "10.1234"],
  ] as const)("%s %s has more than two decimals", (type, raw) => {
    expect(validateThreshold(type, raw)).toBe("Use at most two decimal places.");
  });

  it.each([
    ["STALE", "1"],
    ["STALE", "30"],
    ["STALE", "3600"],
    ["STALE", " 45.5 "],
    ["STALE", "12.34"],
    ["WIDE_SPREAD", "0.5"],
    ["WIDE_SPREAD", "25.25"],
    ["WIDE_SPREAD", "5000"],
  ] as const)("%s %s is valid", (type, raw) => {
    expect(validateThreshold(type, raw)).toBeNull();
  });

  it("exposes units matching the API enum", () => {
    expect(RULE_BOUNDS.STALE.unit).toBe("SECONDS");
    expect(RULE_BOUNDS.WIDE_SPREAD.unit).toBe("BPS");
  });
});
