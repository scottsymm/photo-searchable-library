import { describe, expect, it } from "vitest";
import { bridgeLabel, freshnessLabel, readinessLabel, STAGES } from "./funnel";
import type { SourceOverview } from "../types";

function source(partial: Partial<SourceOverview>): SourceOverview {
  return {
    kind: "apple_photos", display_name: "Apple Photos", readiness: "connected",
    readiness_detail: null, reported_at: null,
    bridge_status: "connected", bridge_last_seen_at: null, authorization_state: "authorized",
    stages: { discovered: 0, ready_to_import: 0, importing: 0, imported: 0, processing: 0, searchable: 0, failed_or_blocked: 0 },
    sync: null, actions: { can_sync: false }, ...partial,
  };
}

describe("STAGES", () => {
  it("covers every funnel key in order", () => {
    expect(STAGES.map((s) => s.key)).toEqual(["discovered", "ready_to_import", "importing", "imported", "processing", "searchable", "failed_or_blocked"]);
  });
  it("marks importing and failed_or_blocked as approximate", () => {
    expect(STAGES.find((s) => s.key === "importing")?.approximate).toBe(true);
    expect(STAGES.find((s) => s.key === "failed_or_blocked")?.approximate).toBe(true);
    expect(STAGES.find((s) => s.key === "searchable")?.approximate).toBe(false);
  });
});

describe("readinessLabel", () => {
  it("labels every readiness state", () => {
    expect(readinessLabel("not_configured")).toBe("Not configured");
    expect(readinessLabel("authorization_required")).toBe("Authorization required");
    expect(readinessLabel("inventory_pending")).toBe("Inventory pending");
    expect(readinessLabel("connected")).toBe("Connected");
    expect(readinessLabel("failed")).toBe("Failed");
  });
});

describe("bridgeLabel", () => {
  it("labels every bridge state", () => {
    expect(bridgeLabel("offline")).toBe("Bridge offline");
    expect(bridgeLabel("authorization_required")).toBe("Photos access required");
    expect(bridgeLabel("inventory_pending")).toBe("Reading Photos library");
    expect(bridgeLabel("connected")).toBe("Connected");
    expect(bridgeLabel("syncing")).toBe("Syncing");
  });
});

describe("freshnessLabel", () => {
  const now = new Date("2026-09-15T15:00:00Z");
  it("treats uploads as live", () => expect(freshnessLabel(source({ kind: "uploads" }), now)).toBe("live"));
  it("flags sources that never reported", () => expect(freshnessLabel(source({}), now)).toBe("never synced"));
  it("relates mounted scans to now", () => {
    expect(freshnessLabel(source({ kind: "mounted_folder", reported_at: "2026-09-15T14:59:00Z" }), now)).toBe("scanned 1 min ago");
    expect(freshnessLabel(source({ kind: "mounted_folder", reported_at: "2026-09-15T13:00:00Z" }), now)).toBe("scanned 2 h ago");
  });
  it("dates bridge-reported totals", () => expect(freshnessLabel(source({ reported_at: "2026-09-15T14:59:16Z" }), now).startsWith("as of last sync ")).toBe(true));
});
