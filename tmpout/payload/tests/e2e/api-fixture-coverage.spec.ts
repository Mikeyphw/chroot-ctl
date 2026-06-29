
import { test, expect } from "@playwright/test";

test("fixture API endpoints expose seeded dashboard, jobs, snapshots, repair, and events data", async ({ request }) => {
  const state = await request.get("/api/state");
  expect(state.ok()).toBeTruthy();
  const stateJson = await state.json();
  expect(Array.isArray(stateJson.chroots.details)).toBeTruthy();
  expect(stateJson.chroots.details.length).toBeGreaterThanOrEqual(4);

  const jobs = await request.get("/api/jobs");
  expect(jobs.ok()).toBeTruthy();
  const jobsJson = await jobs.json();
  expect(jobsJson.jobs.length).toBeGreaterThanOrEqual(5);

  const snapshots = await request.get("/api/snapshots");
  expect(snapshots.ok()).toBeTruthy();
  const snapshotJson = await snapshots.json();
  expect(snapshotJson.items.length).toBeGreaterThanOrEqual(3);

  const repair = await request.get("/api/registry/repair/preview-detailed");
  expect(repair.ok()).toBeTruthy();
  const repairJson = await repair.json();
  expect(repairJson.items.length).toBeGreaterThanOrEqual(3);

  const events = await request.get("/api/events");
  expect(events.ok()).toBeTruthy();
  const eventsJson = await events.json();
  expect(eventsJson.items.length).toBeGreaterThanOrEqual(3);
});
