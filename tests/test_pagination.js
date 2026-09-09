const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "app", "web", "assets", "pagination.js"), "utf8");
const context = vm.createContext({ window: {} });
vm.runInContext(source, context);
const Pagination = context.window.MatrixPagination;

test("page model exposes the requested range and compact page labels", () => {
  const model = Pagination.model(2439, 200, 7);
  assert.equal(model.start, 1201);
  assert.equal(model.end, 1400);
  assert.equal(model.pages, 13);
  assert.deepEqual(Array.from(model.labels), [1, "…", 5, 6, 7, 8, 9, "…", 13]);
});

test("page model clamps invalid pages and keeps an empty list at zero range", () => {
  assert.deepEqual(JSON.parse(JSON.stringify(Pagination.model(0, 200, 9))), {
    total: 0, page: 1, pageSize: 200, pages: 1, start: 0, end: 0, labels: [1],
  });
  assert.equal(Pagination.model(201, 200, 99).page, 2);
});

test("markup matches the unified page-size, page-number, and range layout", () => {
  const html = Pagination.markup(Pagination.model(2439, 200, 7));
  assert.match(html, /页面行数：/);
  assert.match(html, /<option value="200" selected>200<\/option>/);
  assert.match(html, /data-page="7"[^>]*aria-current="page"/);
  assert.match(html, />…<\/span>/);
  assert.match(html, /1201–1400 \/ 2439/);
});
