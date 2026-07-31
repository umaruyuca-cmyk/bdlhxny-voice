package com.stockwise;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * StockWise 应用入口。
 * @MapperScan 扫描 mapper 包下的数据访问接口，使其注册为 Spring Bean。
 */
@SpringBootApplication
@MapperScan("com.stockwise.mapper")
public class StockWiseApplication {

    public static void main(String[] args) {
        SpringApplication.run(StockWiseApplication.class, args);
    }
}
