package com.stockwise.api;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 公开能力目录（脱敏）。
 * 仅返回面向用户展示的 Agent / Skill 名称、状态与文档路径，供前端 Skill 生态页等读取。
 * 不返回任何密钥、内部 URL、服务器 IP、数据库连接或管理信息；状态无法探测时使用 configured/unknown。
 */
@RestController
@RequestMapping("/api/v1/public")
public class PublicCapabilitiesController {

    @GetMapping("/capabilities")
    public Map<String, Object> capabilities() {
        return Map.of(
                "agents", List.of(
                        Map.of("id", "general", "name", "通用研究", "status", "available"),
                        Map.of("id", "stock", "name", "标的研究", "status", "available")),
                "skills", List.of(
                        Map.of("id", "stock", "name", "单标的分析", "status", "available", "docsPath", "/docs/skill"),
                        Map.of("id", "portfolio", "name", "组合分析", "status", "available", "docsPath", "/docs/skill"),
                        Map.of("id", "quant", "name", "量化分析", "status", "available", "docsPath", "/docs/skill"),
                        Map.of("id", "sector", "name", "板块分析", "status", "available", "docsPath", "/docs/skill")));
    }
}
