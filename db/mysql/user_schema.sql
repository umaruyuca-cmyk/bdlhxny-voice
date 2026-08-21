-- =============================================================================
-- MySQL user_schema.sql
-- 认证与 RBAC 全量脚本（在独立 MySQL 库执行，与 PostgreSQL Runtime 无关）。
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '用户主键',
    username      VARCHAR(100) UNIQUE NOT NULL COMMENT '登录用户名',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
    email         VARCHAR(200) COMMENT '邮箱',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台用户账号';

CREATE TABLE IF NOT EXISTS roles (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '角色主键',
    code        VARCHAR(64) UNIQUE NOT NULL COMMENT '角色码，如 USER/ADMIN',
    name        VARCHAR(100) NOT NULL COMMENT '角色显示名',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RBAC 角色';

CREATE TABLE IF NOT EXISTS permissions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '权限主键',
    code        VARCHAR(100) UNIQUE NOT NULL COMMENT '权限码',
    name        VARCHAR(150) NOT NULL COMMENT '权限显示名',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RBAC 权限';

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     BIGINT NOT NULL COMMENT '用户 ID',
    role_id     BIGINT NOT NULL COMMENT '角色 ID',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户-角色绑定';

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       BIGINT NOT NULL COMMENT '角色 ID',
    permission_id BIGINT NOT NULL COMMENT '权限 ID',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
    PRIMARY KEY (role_id, permission_id),
    CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id),
    CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES permissions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色-权限绑定';

-- 基础角色 / 权限种子（可重复执行）
INSERT INTO roles (code, name) VALUES
    ('USER', '普通用户'),
    ('ADMIN', '系统管理员')
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO permissions (code, name) VALUES
    ('AGENT_RUN_READ', '读取自己的 Agent Run'),
    ('KNOWLEDGE_READ', '读取公开知识'),
    ('KNOWLEDGE_WRITE', '维护知识库'),
    ('SYSTEM_USER_READ', '读取系统用户')
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('AGENT_RUN_READ', 'KNOWLEDGE_READ', 'KNOWLEDGE_WRITE')
WHERE r.code = 'USER';

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE r.code = 'ADMIN';

-- 管理员授权须运维显式执行，禁止自动提升首个用户：
-- INSERT IGNORE INTO user_roles (user_id, role_id)
-- SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'ADMIN'
-- WHERE u.username = 'your-admin-username';
