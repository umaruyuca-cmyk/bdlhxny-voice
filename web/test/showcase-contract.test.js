import { readFile, access } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * 结果与证据契约(信息架构 v3 · 两核心页):
 * /results/ 与 /evidence/ 只读统一适配层(SHOWCASE)发布的公开快照;
 * 未发布保持真实空状态;每个汇总数字可下钻到单次运行;
 * 证据链按实际发生顺序,原始 JSON 折叠且只有复制;脱敏边界不因展示需要放宽。
 */

async function readPublic(rel) {
  return readFile(new URL(`../public/${rel}`, import.meta.url), "utf8");
}

test("结果页与证据页共享统一适配层,不各自解析字段", async () => {
  const adapter = await readPublic("docs/showcase-data.js");
  assert.match(adapter, /window\.SHOWCASE/, "适配层挂载为全局 SHOWCASE");
  assert.match(adapter, /METRICS/, "适配层维护全站指标元数据(口径/方向/格式)");
  for (const page of ["results/results.js", "evidence/evidence.js", "docs/home.js"]) {
    const js = await readPublic(page);
    assert.match(js, /window\.SHOWCASE|SC\./, `${page} 消费统一适配层`);
    assert.doesNotMatch(js, /\/showcase-data\/(index|batches|runs)\//, `${page} 不绕过适配层拼数据 URL`);
  }
});

test("未发布即空:索引为空时两核心页保持真实空状态,不渲染模拟数据", async () => {
  // 发布器索引随仓库携带明确空状态(formal_batches 为空数组),页面据此渲染空态;
  // 空索引不是正式数据,禁止向 formal_batches 手填条目
  const index = JSON.parse(await readFile(new URL("../public/showcase-data/index.json", import.meta.url), "utf8"));
  assert.deepEqual(index.formal_batches, [], "发布器索引初始为空");
  assert.equal(index.latest_batch, null, "无最新批次时 latest_batch 为 null");
  const results = await readPublic("results/index.html");
  assert.match(results, /尚无正式实验结果/, "结果页空状态文案存在");
  assert.match(results, /不会用演示数据或估算填充/, "空状态声明不填充演示数据");
  const evidence = await readPublic("evidence/index.html");
  assert.match(evidence, /尚无公开发布的运行/, "证据页空状态文案存在");
  const adapter = await readPublic("docs/showcase-data.js");
  assert.match(adapter, /return null;/, "适配层对缺失文件返回 null(不抛错、不兜底假数据)");
});

test("结果页:固定条件/样本规模/指标/变体对比/分场景/失败类型/代表案例齐备", async () => {
  const js = await readPublic("results/results.js");
  for (const block of ["designBlock", "sampleBlock", "metricsBlock", "compareBlock", "sceneBlock", "failureBlock", "caseBlock"]) {
    assert.ok(js.includes(block), `结果页缺少渲染区块 ${block}`);
  }
  // 指标必须带分母与方向口径
  assert.match(js, /分母/, "指标表头展示分母");
  assert.match(js, /越高越好|越低越好/, "指标标注方向口径");
  assert.match(js, /有效运行/, "样本口径使用有效运行");
  assert.match(js, /无效运行/, "无效运行单列,不冒充失败样本");
  // 分场景矩阵的 0 总量格显示未记录而非 0%
  assert.match(js, /未记录/, "缺失值显示未记录");
  // 下钻链接
  assert.match(js, /\/evidence\/\?batch=/, "汇总下钻到证据索引");
  assert.match(js, /\/evidence\/run\/\?id=/, "代表案例下钻到证据链");
});

test("证据链 11 段按实际发生顺序,段落编号 01–11 连续", async () => {
  const js = await readPublic("evidence/evidence.js");
  for (let no = 1; no <= 11; no += 1) {
    assert.ok(js.includes(`"${String(no).padStart(2, "0")}"`), `证据链第 ${String(no).padStart(2, "0")} 段缺失`);
  }
  const run = await readPublic("evidence/run.html");
  assert.match(run, /crumb[\s\S]*?\/evidence\/[\s\S]*?证据索引/, "详情页有返回索引入口");
  assert.match(run, /id="runDetail"/, "详情页有渲染容器");
});

test("证据展示不泄露思维链/密钥/金标;原始 JSON 折叠且仅复制", async () => {
  const js = await readPublic("evidence/evidence.js");
  assert.match(js, /不含模型内部思维链/, "声明不展示思维链");
  assert.match(js, /决策依据摘要/, "步骤时间线定位为决策依据摘要");
  assert.match(js, /金标答案不在公开字段/, "声明金标不公开");
  assert.match(js, /copy-btn/, "仅提供复制按钮");
  assert.doesNotMatch(js, /Blob|createObjectURL|download/, "不提供下载实现");
  assert.doesNotMatch(js, /reproduc|复现命令|重新运行运行/, "不提供复现/重跑");
  // 原始 JSON 段默认折叠(第 11 段 open=false)
  const rawSection = js.slice(js.indexOf('"11", "原始 JSON'), js.indexOf('"11", "原始 JSON') + 900);
  assert.match(rawSection, /, false\)/, "原始 JSON 段默认折叠");
});

test("证据索引行字段口径:运行编号/用例/变体/状态/判定/步骤数/耗时/时间", async () => {
  const js = await readPublic("evidence/evidence.js");
  for (const col of ["运行编号", "用例", "实验变体", "状态", "判定", "步骤数", "耗时", "发生时间"]) {
    assert.ok(js.includes(col), `证据索引缺少列:${col}`);
  }
  assert.match(js, /未记录/, "缺失字段显示未记录");
  assert.match(js, /PAGE_SIZE/, "索引分页实现存在");
  assert.match(js, /上一页|下一页/, "分页控件存在");
});

test("脱敏与发布白名单未被削弱:schema 禁止字段扫描仍在发布链生效", async () => {
  const publisher = await readPublic("../scripts/publish-showcase.mjs");
  assert.match(publisher, /scanForbidden/, "发布器仍执行禁止字段扫描");
  assert.match(publisher, /scanSensitive/, "发布器仍执行敏感内容扫描");
  assert.match(publisher, /SENSITIVE_RULES/, "敏感规则清单仍在");
  const validator = await readFile(new URL("../schema/validate.mjs", import.meta.url), "utf8");
  assert.match(validator, /scanForbidden/, "校验器保留禁止字段扫描");
  const schema = await readFile(new URL("../schema/showcase-data/run.schema.json", import.meta.url), "utf8");
  for (const banned of ["system_prompt", "api_key", "password", "session_token"]) {
    assert.ok(!schema.includes(`"${banned}"`), `run schema 不得定义禁止字段 ${banned}`);
  }
});

test("脱敏语料与数据文件仍在公开快照内(底层展示数据未被误删)", async () => {
  for (const file of ["showcase-data/cases.json", "showcase-data/tools.json", "showcase-data/context-library.json", "showcase-data/publications/index.json"]) {
    await access(new URL(`../public/${file}`, import.meta.url));
  }
});
