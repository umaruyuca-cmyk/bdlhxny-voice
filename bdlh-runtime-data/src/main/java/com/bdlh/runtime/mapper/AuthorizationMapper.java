package com.bdlh.runtime.mapper;

import com.baomidou.dynamic.datasource.annotation.DS;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Param;

/**
 * 读取 MySQL RBAC 关系并为新用户分配默认角色。
 */
@DS("mysql")
public interface AuthorizationMapper {

    /**
     * 判断用户是否通过任一角色拥有指定权限。
     */
    @Select("""
            SELECT EXISTS(
                SELECT 1
                FROM user_roles ur
                JOIN role_permissions rp ON rp.role_id = ur.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE ur.user_id = #{userId}
                  AND p.code = #{permissionCode}
            )
            """)
    boolean hasPermission(@Param("userId") Long userId,
                          @Param("permissionCode") String permissionCode);

    /**
     * 给用户补齐普通用户角色，INSERT IGNORE 保证重复执行安全。
     */
    @Insert("""
            INSERT IGNORE INTO user_roles (user_id, role_id)
            SELECT #{userId}, id FROM roles WHERE code = 'USER'
            """)
    int assignDefaultRole(@Param("userId") Long userId);
}
