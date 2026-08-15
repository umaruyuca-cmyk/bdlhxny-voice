package com.bdlh.runtime.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.bdlh.runtime.dto.SystemUserView;
import com.bdlh.runtime.entity.User;
import com.bdlh.runtime.mapper.UserMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/**
 * 系统用户查询服务，隔离 MySQL 实体并确保密码摘要不会进入接口响应。
 */
@Service
public class SystemUserService {

    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 100;

    private final UserMapper userMapper;

    public SystemUserService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    /**
     * 按创建时间倒序返回受限数量的系统用户，防止 Swagger 调试时误拉取全表。
     */
    public List<SystemUserView> list(Integer limit) {
        // 1. 将外部数量约束在安全范围内
        int boundedLimit = limit == null ? DEFAULT_LIMIT : Math.max(1, Math.min(limit, MAX_LIMIT));
        // 2. 查询并转换为不包含密码摘要的对外视图
        return userMapper.selectList(new LambdaQueryWrapper<User>()
                        .orderByDesc(User::getCreatedAt)
                        .last("LIMIT " + boundedLimit))
                .stream()
                .map(SystemUserView::from)
                .toList();
    }

    /**
     * 按主键查询系统用户，不存在时返回标准的 HTTP 404。
     */
    public SystemUserView get(Long id) {
        User user = userMapper.selectById(id);
        if (user == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "系统用户不存在: " + id);
        }
        return SystemUserView.from(user);
    }
}
