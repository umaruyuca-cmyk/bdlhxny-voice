-- ============================================================
-- MySQL 用户模块的全量建表和初始角色权限脚本。
-- 在 MySQL 的 platform 库执行
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email         VARCHAR(200),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 2. RBAC：角色、权限及关联表
-- 角色和权限独立建表，避免把可变权限硬编码进 users 表或 JWT。
-- ============================================================
CREATE TABLE IF NOT EXISTS roles (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(64) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS permissions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(100) UNIQUE NOT NULL,
    name        VARCHAR(150) NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role_id, permission_id),
    CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id),
    CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES permissions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 基础角色和权限种子可重复执行，不覆盖人工配置。
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

-- 普通用户保留当前已开放的登录后能力。
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('AGENT_RUN_READ', 'KNOWLEDGE_READ', 'KNOWLEDGE_WRITE')
WHERE r.code = 'USER';

-- 管理员拥有当前权限集合，后续新增权限时可继续补充该种子段。
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE r.code = 'ADMIN';

-- 新项目不执行任何存量用户角色补齐；新注册用户由 AuthService 同步分配普通用户角色。

-- 管理员授权示例（必须由运维明确执行，禁止自动把首个用户升为管理员）：
-- 示例 SQL：INSERT IGNORE INTO user_roles (user_id, role_id)
-- 示例 SQL：SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'ADMIN'
-- 示例 SQL：WHERE u.username = 'your-admin-username';
