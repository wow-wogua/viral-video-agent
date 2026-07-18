import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


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


const reviewDataPath = path.resolve(argument("--review-data"));
const holdoutManifestPath = path.resolve(argument("--holdout-manifest"));
const outputPath = path.resolve(argument("--output"));
const previewDir = path.resolve(argument("--preview-dir"));
const reviewDataBytes = await fs.readFile(reviewDataPath);
const manifestBytes = await fs.readFile(holdoutManifestPath);
const reviewData = JSON.parse(reviewDataBytes.toString("utf8"));
const manifest = JSON.parse(manifestBytes.toString("utf8"));
const reviewItems = reviewData.review_items;
const evidenceRows = reviewData.evidence_rows;

if (!Array.isArray(reviewItems) || reviewItems.length < 40 || reviewItems.length > 80) {
  throw new Error("blind holdout review item count must stay within 40-80");
}

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("审核说明");
const reviews = workbook.worksheets.add("账号主题盲审");
const evidence = workbook.worksheets.add("投稿证据");

instructions.showGridLines = false;
reviews.showGridLines = false;
evidence.showGridLines = false;

instructions.getRange("A1:H1").merge();
instructions.getRange("A1").values = [["P0-C v3 新盲评审核说明"]];
instructions.getRange("A1:H1").format = {
  fill: "#183B56",
  font: { bold: true, color: "#FFFFFF", size: 18 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
instructions.getRange("A1:H1").format.rowHeight = 34;

instructions.getRange("A3:B7").values = [
  ["项目", "值"],
  ["预计审核数量", reviewItems.length],
  ["已完成", null],
  ["未完成", null],
  ["状态", null],
];
instructions.getRange("B5").formulas = [[`=COUNTIF('账号主题盲审'!$R$2:$R$${reviewItems.length + 1},TRUE)`]];
instructions.getRange("B6").formulas = [["=B4-B5"]];
instructions.getRange("B7").formulas = [["=IF(B6=0,\"可提交\",\"待完成\")"]];
instructions.getRange("A3:B3").format = {
  fill: "#2E6F95",
  font: { bold: true, color: "#FFFFFF" },
};
instructions.getRange("A4:A7").format.font = { bold: true, color: "#183B56" };
instructions.getRange("B4:B6").format.numberFormat = "#,##0";
instructions.getRange("A3:B7").format.borders = {
  preset: "inside",
  style: "thin",
  color: "#D7E2EA",
};

instructions.getRange("A9:H9").merge();
instructions.getRange("A9").values = [["填写规则"]];
instructions.getRange("A9:H9").format = {
  fill: "#DCEAF4",
  font: { bold: true, color: "#183B56" },
};
instructions.getRange("A10:H17").values = [
  ["字段", "允许值 / 要求", null, null, null, null, null, null],
  ["human_relevance", "relevant / irrelevant / uncertain", null, null, null, null, null, null],
  ["human_specialization", "high / medium / low / unknown", null, null, null, null, null, null],
  ["human_role", "specialist / generalist / official / media / educator / reviewer / service / aggregator / unrelated / unknown", null, null, null, null, null, null],
  ["human_reason", "必须说明账号与主题的持续关系、边界或证据不足；不能为空", null, null, null, null, null, null],
  ["review_complete", "确认前三个标签和 reason 后选择 TRUE", null, null, null, null, null, null],
  ["审核口径", "主题相关不等于核心竞品；同时判断专业聚焦、角色、持续性和影响力", null, null, null, null, null, null],
  ["禁止事项", "不要参考或猜测系统分数、选择状态、旧标签或 Gate 指标", null, null, null, null, null, null],
];
instructions.getRange("A10:H10").format = {
  fill: "#2E6F95",
  font: { bold: true, color: "#FFFFFF" },
};
instructions.getRange("A10:H17").format.wrapText = true;
instructions.getRange("A10:A17").format.font = { bold: true, color: "#183B56" };

instructions.getRange("A19:B24").values = [
  ["审计元数据", "值"],
  ["schema_version", reviewData.schema_version],
  ["review_data_sha256", sha256(reviewDataBytes)],
  ["holdout_manifest_sha256", sha256(manifestBytes)],
  ["code_commit_sha", manifest.code_commit_sha ?? ""],
  ["review_standard_sheet", reviewData.review_standard_sheet ?? "审核说明"],
];
instructions.getRange("A19:B19").format = {
  fill: "#5A7184",
  font: { bold: true, color: "#FFFFFF" },
};
instructions.getRange("A19:B24").format = {
  wrapText: true,
  font: { size: 9 },
};
instructions.getRange("A1:A24").format.columnWidth = 24;
instructions.getRange("B1:B24").format.columnWidth = 72;
instructions.getRange("C1:H24").format.columnWidth = 4;

const reviewHeaders = [
  "review_id", "keyword_id", "keyword", "category", "intent_definition",
  "allowed_subtopics_summary", "exclusion_rules_summary", "creator_name", "creator_mid",
  "neutral_public_info", "sample_upload_count", "recent_30d_upload_count",
  "recent_90d_upload_count", "human_relevance", "human_specialization", "human_role",
  "human_reason", "review_complete",
];
reviews.getRange(`A1:R${reviewItems.length + 1}`).values = [
  reviewHeaders,
  ...reviewItems.map((item) => reviewHeaders.map((header) => item[header] ?? null)),
];
reviews.getRange("A1:R1").format = {
  fill: "#183B56",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
reviews.getRange("A1:R1").format.rowHeight = 48;
reviews.getRange(`A2:R${reviewItems.length + 1}`).format.verticalAlignment = "top";
reviews.getRange(`A2:R${reviewItems.length + 1}`).format.rowHeight = 36;
reviews.getRange(`C2:J${reviewItems.length + 1}`).format.wrapText = true;
reviews.getRange(`N2:R${reviewItems.length + 1}`).format = {
  fill: "#FFF5CC",
  wrapText: true,
};
reviews.getRange(`N2:N${reviewItems.length + 1}`).dataValidation = {
  rule: { type: "list", values: reviewData.allowed_values.human_relevance },
};
reviews.getRange(`O2:O${reviewItems.length + 1}`).dataValidation = {
  rule: { type: "list", values: reviewData.allowed_values.human_specialization },
};
reviews.getRange(`P2:P${reviewItems.length + 1}`).dataValidation = {
  rule: { type: "list", values: reviewData.allowed_values.human_role },
};
reviews.getRange(`R2:R${reviewItems.length + 1}`).dataValidation = {
  rule: { type: "list", values: ["TRUE", "FALSE"] },
};
reviews.getRange(`R2:R${reviewItems.length + 1}`).conditionalFormats.add(
  "containsText",
  { text: "FALSE", format: { fill: "#FDE2E1" } },
);
reviews.getRange(`R2:R${reviewItems.length + 1}`).conditionalFormats.add(
  "containsText",
  { text: "TRUE", format: { fill: "#DDF3E4" } },
);
reviews.freezePanes.freezeRows(1);
reviews.freezePanes.freezeColumns(2);
reviews.tables.add(`A1:R${reviewItems.length + 1}`, true, "P0CV3ReviewTable");
const reviewWidths = {
  A: 24, B: 14, C: 18, D: 12, E: 36, F: 34, G: 34, H: 22, I: 16,
  J: 34, K: 12, L: 12, M: 12, N: 16, O: 18, P: 16, Q: 42, R: 16,
};
for (const [column, width] of Object.entries(reviewWidths)) {
  reviews.getRange(`${column}1:${column}${reviewItems.length + 1}`).format.columnWidth = width;
}

const evidenceHeaders = [
  "review_id", "evidence_sequence", "evidence_type", "title", "description_summary",
  "published_at", "frozen_snapshot_metrics", "source_url", "evidence_reference",
];
evidence.getRange(`A1:I${evidenceRows.length + 1}`).values = [
  evidenceHeaders,
  ...evidenceRows.map((item) => evidenceHeaders.map((header) => item[header] ?? null)),
];
evidence.getRange("A1:I1").format = {
  fill: "#183B56",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
evidence.getRange("A1:I1").format.rowHeight = 40;
evidence.getRange(`A2:I${evidenceRows.length + 1}`).format.verticalAlignment = "top";
evidence.getRange(`A2:I${evidenceRows.length + 1}`).format.rowHeight = 34;
evidence.getRange(`D2:E${evidenceRows.length + 1}`).format.wrapText = true;
evidence.getRange(`F2:F${evidenceRows.length + 1}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
evidence.freezePanes.freezeRows(1);
evidence.freezePanes.freezeColumns(1);
evidence.tables.add(`A1:I${evidenceRows.length + 1}`, true, "P0CV3EvidenceTable");
const evidenceWidths = { A: 24, B: 12, C: 20, D: 54, E: 48, F: 22, G: 24, H: 48, I: 30 };
for (const [column, width] of Object.entries(evidenceWidths)) {
  evidence.getRange(`${column}1:${column}${evidenceRows.length + 1}`).format.columnWidth = width;
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, fileName, range] of [
  ["审核说明", "instructions.png", "A1:H24"],
  ["账号主题盲审", "reviews.png", `A1:R${Math.min(reviewItems.length + 1, 12)}`],
  ["投稿证据", "evidence.png", `A1:I${Math.min(evidenceRows.length + 1, 20)}`],
]) {
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, fileName),
    new Uint8Array(await preview.arrayBuffer()),
  );
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({
  output: outputPath,
  reviewItemCount: reviewItems.length,
  evidenceRowCount: evidenceRows.length,
  reviewDataSha256: sha256(reviewDataBytes),
  holdoutManifestSha256: sha256(manifestBytes),
}));
