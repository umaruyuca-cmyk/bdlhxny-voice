#!/usr/bin/env node
/**
 * 工作项目图表导入器(脱敏版)。
 *
 * 从本地源目录读取内部流程图 SVG,做脱敏替换后写入 public/work/diagrams/,
 * 供 /work/ 页面嵌入。公开站只保留脱敏产物,源图不进仓库。
 *
 * 脱敏原则:
 *   - 移除行方服务编码(MBSD、MbsdNl、JZH 前缀)、内部接口路径、端口、机构号
 *   - 内部类名 / 方法名 / 表名 / 字段名 → 概念化中文名
 *   - 保留:业务流程、合作方名称(与公开简历同级)、风控阈值、设计决策
 *
 * 用法: node scripts/import-work-diagrams.mjs [源目录]
 *   源目录默认 D:/slr/slr(包含 slr/jingloan/jdong-cloud 三处图源)。
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC_ROOT = process.argv[2] || "D:/slr/slr";
const OUT_DIR = path.join(WEB_ROOT, "public", "work", "diagrams");

/** 源图 → 输出文件名 */
const SOURCES = [
  { from: "slr/dev-zcy/slr-cloud/doc/b2b_loan/B2B法透全链路流程图.svg", to: "b2b-legal-overdraft.svg" },
  { from: "slr/dev-zcy/slr-cloud/doc/b2b_loan/B2B商票模式全链路流程图.svg", to: "b2b-commercial-bill.svg" },
  { from: "slr/dev-zcy/slr-cloud/doc/b2b_loan/合同审核流程_汇报用.svg", to: "contract-review.svg" },
  { from: "jingloan/jingloan/doc/京e贷贷款服务全链路流程图.svg", to: "bob-loan-service.svg" },
  { from: "jdong-cloud/jdong-cloud/document/银行能力开放平台全链路架构图.svg", to: "open-platform-architecture.svg" },
];

/** 全局脱敏规则(所有图通用),按顺序应用 */
const GLOBAL_RULES = [
  // 行方服务编码整段移除(含前导分隔符)
  [/\s*·\s*(?:MBSD_LOAN[JZH_0-9-]*|JZH-[0-9-]+|MbsdNl-[0-9-]+)\b/g, ""],
  [/（JZH-[0-9-]+）/g, ""],
  // 端口 / 机构号 / 内部通道名
  [/\s*·\s*8201/g, ""],
  [/\s*·\s*8401/g, ""],
  [/\s*·\s*8880/g, ""],
  [/（8848）/g, ""],
  [/BRANCH_ID 31001[ /]*/g, ""],
  [/szFactory/g, "统一通道"],
  [/jingloan/g, "贷款服务"],
  // 通用技术名概念化
  [/cron4j/g, "轻量调度器"],
  [/task_info/g, "任务表"],
  [/fundBizStep=\d/g, "对应资金环节"],
  [/ \/fdif\/manage\/api\/function/g, ""],
];

/** 每张图各自的规则 */
const FILE_RULES = {
  "contract-review.svg": [
    [/@Async 异步执行/g, "异步执行"],
    [/@Async/g, "异步任务"],
  ],
  "b2b-legal-overdraft.svg": [
    [/\/trade\/apply 接口/g, "支付申请接口"],
    [/\/payment\/confirm 接口/g, "支付确认接口"],
    [/fundBizStep/g, "资金环节"],
  ],
  "b2b-commercial-bill.svg": [
    [/commercialTicketNumber/g, "商票编号"],
    [/\/payment\/confirm 请求带/g, "支付确认接口请求带"],
    [/assertCanRegisterDraft/g, "商票入库模式校验"],
    [/updateDraftInfo/g, "商票信息登记"],
    [/draftRegistered/g, "已有商票入库记录"],
    [/draftNo\s*\/\s*draftAmount/g, "商票号 / 票面金额"],
    [/draftNo\s*\+\s*draftAmount/g, "商票号+票面金额"],
    [/commercial_bill_transfer/g, "商票转让台账"],
    [/commercial_bill_info/g, "商票台账"],
    [/pushCdNo\s*\/\s*pushBillAmt/g, "推送票号 / 推送金额"],
    [/supplementStatus=未补录/g, "补录状态=未补录"],
    [/REPAY_COMMERCIAL_BILL/g, "到期兑付转账"],
    [/REPAY_PRI/g, "还款确认转账"],
    [/alreadyRepayAmt/g, "已还累计"],
    [/commercialBillDueDateTransferJob/g, "商票到期转账任务"],
    [/resolveAlreadyRepayAmt/g, "兑付状态修正"],
    [/dueDt/g, "到期日"],
    [/flowMode=商票 写入 b2b_order_flow/g, "融资模式随流程记录初始化并继承"],
    [/b2b_order_flow/g, "流程记录表"],
    [/（step=\d）/g, ""],
    [/fundBizStep=\d/g, "对应资金环节"],
  ],
  "bob-loan-service.svg": [
    [/\/getLoanAmount · quota\/query/g, "统一远程门面"],
    [/useCreditApply\s*\/\s*Result/g, "提款申请 / 结果查询"],
    [/useCreditApply\(\)\/useCreditResult\(\)/g, "提款申请 / 结果查询接口"],
    [/loan\/provide/g, "放款接口"],
    [/loanRepay\/result/g, "放还款结果接口"],
    [/repayPlan\/query/g, "还款计划接口"],
    [/repayTrial\/bfLoan/g, "贷前试算接口"],
    [/quota\/query/g, "额度查询接口"],
    [/loanRecovery/g, "还款回收"],
    [/&gt;quota \/ query&lt;/g, "&gt;额度查询&lt;"],
    [/&gt;repayPlan · repayTrial&lt;/g, "&gt;还款计划 · 试算&lt;"],
    [/imageOcrRecognize/g, "OCR 识别接口"],
    [/bioIdentify/g, "银行生物识别"],
    [/mobile\/verify/g, "运营商核验"],
    [/smsVerify/g, "短信核验"],
    [/CurrencyConverter/g, "统一换算器"],
    [/Spring Boot 单体 · /g, "Spring Boot 单体应用 · "],
    [/000000 \/ 00000 · /g, "双返回码口径 · "],
    [/（body\/BODY 大小写兼容）/g, "（大小写兼容）"],
    [/BODY 大小写兼容/g, "大小写兼容"],
    [/银行 银行生物识别/g, "银行生物识别"],
  ],
  "open-platform-architecture.svg": [
    [/ApiFunctionController · \/manage\/api\/function\/\*\*/g, "对外统一 API（能力编排层）"],
    [/\/manage\/api\/function\/?\*?/g, "统一能力 API"],
    [/bobbankhz · 14 类/g, "杭州分行客户端模块"],
    [/bobbank · 82 类/g, "总行客户端 · 80+ 接口封装"],
    [/（bobbankhz · 76 文件）/g, "（杭州分行客户端 · 76 文件）"],
    [/风控 CreditReview · 授信 · 放款 LoanProvide · 还款 LoanRepay · 绑卡/g, "风控 · 授信 · 放款 · 还款 · 绑卡"],
    [/三层报文头（BobAcc SysHead\/AppHead\/LocalHead）/g, "三层银行报文头"],
    [/8851 报文组装/g, "分行报文组装"],
    [/deepocr · jdocr/g, "多家 OCR 服务商"],
    [/易道博识 DeepOCR · 影像平台/g, "OCR / 影像服务"],
    [/edms · sunecmdm/g, "影像平台对接"],
    [/ums_resource \+ ums_role \+ 关联表/g, "权限表族（资源 / 角色 / 关联）"],
    [/initResourceRolesMap 聚合/g, "聚合构建"],
    [/Redis hash（auth:resource:roles）/g, "Redis 资源角色映射"],
    [/jwk-set-uri/g, "公钥端点"],
    [/jwt\.jks/g, "密钥库"],
    [/X-User-Header/g, "用户信息头"],
    [/AuthGlobalFilter/g, "全局过滤器"],
    [/AuthorizationManager/g, "鉴权管理器"],
    [/（auth）/g, "认证中心"],
    [/Vue 3 管理后台（ui）/g, "Vue 3 管理后台"],
    [/pre-platform 模块/g, "贷前平台模块"],
    [/客户定制分支：山鹰授信 \/ 1688 对接（订单 \+ 签章）/g, "客户定制分支（行业客户授信 / 1688 对接）"],
    [/bobbank \/ bobbankhz 客户端/g, "总行 / 杭州分行客户端"],
    [/贷款服务（贷款服务）/g, "贷款服务"],
    [/（度小满渠道 · 贷款服务）/g, "（度小满渠道）"],
    [/统一通道 HTTP 通道/g, "统一通道"],
  ],
};

const cleanup = (s) => s.replace(/\s*·\s*·\s*/g, " · ").replace(/\s*·\s*·\s*/g, " · ").replace(/·\s*<\/tspan>/g, "</tspan>").replace(/·\s*✓/g, "✓");

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  for (const { from, to } of SOURCES) {
    const src = path.join(SRC_ROOT, from);
    let svg = await readFile(src, "utf8");
    for (const [pattern, replacement] of GLOBAL_RULES) svg = svg.replace(pattern, replacement);
    for (const [pattern, replacement] of FILE_RULES[to] || []) svg = svg.replace(pattern, replacement);
    svg = cleanup(svg);
    await writeFile(path.join(OUT_DIR, to), svg, "utf8");
    console.log(`sanitized: ${from} -> public/work/diagrams/${to}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
