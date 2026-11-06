import { describe, it, expect } from "vitest";
import { money, pct } from "../src/app/utils";
describe("financial display", () => {
  it("preserves tiny prices", () =>
    expect(money(0.00000012)).not.toBe("$0.00"));
  it("does not invent missing values", () =>
    expect(money(null)).toBe("Unavailable"));
  it("formats decimal returns", () => expect(pct(0.125)).toBe("+12.50%"));
  it("handles nonfinite values", () => expect(pct(NaN)).toBe("—"));
});
