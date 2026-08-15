package com.bdlh.runtime.config;

import io.swagger.v3.oas.annotations.OpenAPIDefinition;
import io.swagger.v3.oas.annotations.info.Info;
import org.springframework.context.annotation.Configuration;

/**
 * BDLH Agent Runtime OpenAPI 文档元数据配置，为 Scalar 文档页提供统一的中文标题与版本说明。
 */
@Configuration
@OpenAPIDefinition(
        info = @Info(
                title = "BDLH Agent Runtime API",
                version = "v1",
                description = "BDLH Agent Runtime 智能投资分析与系统管理接口"
        )
)
public class OpenApiConfig {
}
