package com.stockwise.dto;

import com.stockwise.entity.User;
import io.swagger.v3.oas.annotations.media.Schema;

import java.time.LocalDateTime;

/**
 * 系统用户的对外视图，只返回管理页面需要的非敏感字段。
 */
@Schema(description = "系统用户信息")
public record SystemUserView(
        @Schema(description = "用户 ID", example = "1")
        Long id,
        @Schema(description = "用户名", example = "admin")
        String username,
        @Schema(description = "邮箱", example = "admin@example.com")
        String email,
        @Schema(description = "创建时间")
        LocalDateTime createdAt,
        @Schema(description = "更新时间")
        LocalDateTime updatedAt
) {

    /**
     * 从持久化实体构造安全视图，避免 passwordHash 被接口序列化。
     */
    public static SystemUserView from(User user) {
        return new SystemUserView(
                user.getId(),
                user.getUsername(),
                user.getEmail(),
                user.getCreatedAt(),
                user.getUpdatedAt()
        );
    }
}
