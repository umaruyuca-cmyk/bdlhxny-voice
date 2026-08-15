package com.bdlh.runtime;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * BDLH Agent Runtime 应用入口。
 * @MapperScan 扫描 mapper 包下的数据访问接口，使其注册为 Spring Bean。
 */
@SpringBootApplication
@MapperScan("com.bdlh.runtime.mapper")
public class AgentRuntimeApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentRuntimeApplication.class, args);
    }
}
