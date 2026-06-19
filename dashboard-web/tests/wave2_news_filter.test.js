import test from "node:test";
import assert from "node:assert/strict";
import { sortStocksBySentiment } from "../src/display.js";

test("sentiment sort keeps negative neutral positive labels available", () => {
  const rows = [
    { s: { name: "A", sent: "부정", sscore: 10 } },
    { s: { name: "B", sent: "중립", sscore: 50 } },
    { s: { name: "C", sent: "긍정", sscore: 90 } },
  ];
  const result = sortStocksBySentiment(rows);
  assert.deepEqual(result.map((row) => row.s.sent), ["긍정", "중립", "부정"]);
});
