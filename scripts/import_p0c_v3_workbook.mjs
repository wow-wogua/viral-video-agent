import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";


function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) {
    throw new Error(`missing required argument: ${name}`);
  }
  return process.argv[index + 1];
}


function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}


function normalizedBoolean(value) {
  if (value === true || value === false) return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return null;
}


const workbookPath = path.resolve(argument("--workbook"));
const outputPath = path.resolve(argument("--output"));
const workbookBytes = await fs.readFile(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const reviewSheet = workbook.worksheets.getItem("账号主题盲审");
const instructions = workbook.worksheets.getItem("审核说明");
const used = reviewSheet.getUsedRange(true).values;
if (!Array.isArray(used) || used.length < 2) {
  throw new Error("review workbook does not contain review rows");
}
const headers = used[0].map((value) => String(value ?? "").trim());
const requiredHeaders = [
  "review_id", "keyword_id", "creator_mid", "human_relevance",
  "human_specialization", "human_role", "human_reason", "review_complete",
];
for (const header of requiredHeaders) {
  if (!headers.includes(header)) throw new Error(`missing review column: ${header}`);
}
const index = Object.fromEntries(headers.map((header, position) => [header, position]));
const reviews = [];
const errors = [];
const allowed = {
  human_relevance: new Set(["relevant", "irrelevant", "uncertain"]),
  human_specialization: new Set(["high", "medium", "low", "unknown"]),
  human_role: new Set([
    "specialist", "generalist", "official", "media", "educator", "reviewer",
    "service", "aggregator", "unrelated", "unknown",
  ]),
};
for (let rowIndex = 1; rowIndex < used.length; rowIndex += 1) {
  const row = used[rowIndex];
  const reviewId = String(row[index.review_id] ?? "").trim();
  if (!reviewId) continue;
  const review = {
    review_id: reviewId,
    keyword_id: String(row[index.keyword_id] ?? "").trim(),
    creator_mid: String(row[index.creator_mid] ?? "").trim(),
    human_relevance: String(row[index.human_relevance] ?? "").trim() || null,
    human_specialization: String(row[index.human_specialization] ?? "").trim() || null,
    human_role: String(row[index.human_role] ?? "").trim() || null,
    human_reason: String(row[index.human_reason] ?? "").trim(),
    review_complete: normalizedBoolean(row[index.review_complete]),
  };
  for (const field of ["human_relevance", "human_specialization", "human_role"]) {
    if (!allowed[field].has(review[field])) {
      errors.push(`row ${rowIndex + 1}: invalid ${field}`);
    }
  }
  if (!review.human_reason) errors.push(`row ${rowIndex + 1}: human_reason is required`);
  if (review.review_complete !== true) {
    errors.push(`row ${rowIndex + 1}: review_complete must be TRUE`);
  }
  if (review.human_relevance === "relevant" && review.human_specialization === "unknown") {
    errors.push(`row ${rowIndex + 1}: relevant cannot use unknown specialization`);
  }
  if (
    review.human_relevance === "irrelevant"
    && ["high", "medium"].includes(review.human_specialization)
  ) {
    errors.push(`row ${rowIndex + 1}: irrelevant cannot use high/medium specialization`);
  }
  reviews.push(review);
}
if (reviews.length < 40 || reviews.length > 80) {
  errors.push(`review row count ${reviews.length} is outside 40-80`);
}
if (new Set(reviews.map((review) => review.review_id)).size !== reviews.length) {
  errors.push("duplicate review_id values found");
}

const metadataRows = instructions.getRange("A20:B24").values;
const metadata = Object.fromEntries(
  metadataRows.map((row) => [String(row[0] ?? "").trim(), String(row[1] ?? "").trim()]),
);
for (const key of [
  "schema_version", "review_data_sha256", "holdout_manifest_sha256", "code_commit_sha",
]) {
  if (!metadata[key]) errors.push(`missing workbook metadata: ${key}`);
}
if (errors.length) {
  throw new Error(`review workbook validation failed (${errors.length}): ${errors.slice(0, 8).join("; ")}`);
}

const output = {
  schema_version: "p0c-v3-human-review-import.p0.1",
  imported_at: new Date().toISOString(),
  source_workbook: workbookPath,
  source_workbook_sha256: sha256(workbookBytes),
  review_data_sha256: metadata.review_data_sha256,
  holdout_manifest_sha256: metadata.holdout_manifest_sha256,
  code_commit_sha: metadata.code_commit_sha,
  reviewer_count: 1,
  review_count: reviews.length,
  conflict_count: 0,
  reviews,
};
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ output: outputPath, reviewCount: reviews.length, errors: 0 }));
