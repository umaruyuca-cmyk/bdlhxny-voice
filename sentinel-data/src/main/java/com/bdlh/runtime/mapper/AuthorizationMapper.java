package com.bdlh.runtime.mapper;

import com.baomidou.dynamic.datasource.annotation.DS;
import org.apache.ibatis.annotations.Param;

/**
 * 读取 MySQL RBAC 关系并为新用户分配默认角色。
 * SQL 定义在 {@code mapper/AuthorizationMapper.xml}。
 */
@DS("mysql")
public interface AuthorizationMapper {

    /**
     * 判断用户是否通过任一角色拥有指定权限。
     */
    boolean hasPermission(@Param("userId") Long userId,
                          @Param("permissionCode") String permissionCode);

    /**
     * 给用户补齐普通用户角色，INSERT IGNORE 保证重复执行安全。
     */
    int assignDefaultRole(@Param("userId") Long userId);
}
