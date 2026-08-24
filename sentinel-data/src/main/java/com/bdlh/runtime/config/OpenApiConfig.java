package com.bdlh.runtime.config;

import io.swagger.v3.oas.annotations.OpenAPIDefinition;
import io.swagger.v3.oas.annotations.info.Info;
import org.springframework.context.annotation.Configuration;

/**
 * 用户与金融事实数据 API 的 OpenAPI 元数据配置，为 Scalar 文档页提供统一的中文标题与版本说明。
 */
@Configuration
@OpenAPIDefinition(
        info = @Info(
                title = "BDLH Runtime Data API",
                version = "v1",
                description = "认证、用户金融事实维护，以及供 Python 编排服务受控读取的数据接口"
        )
)
public class OpenApiConfig {
}
