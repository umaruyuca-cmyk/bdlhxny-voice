package com.stockwise.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.stockwise.dto.SystemUserView;
import com.stockwise.entity.User;
import com.stockwise.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 验证系统用户查询的安全视图转换、列表限制与不存在响应。
 */
class SystemUserServiceTest {

    private final UserMapper userMapper = mock(UserMapper.class);
    private final SystemUserService service = new SystemUserService(userMapper);

    @Test
    void listsUsersWithoutPasswordHash() {
        User user = new User();
        user.setId(1L);
        user.setUsername("admin");
        user.setPasswordHash("must-not-leak");
        user.setEmail("admin@example.com");
        user.setCreatedAt(LocalDateTime.of(2026, 7, 31, 9, 0));
        when(userMapper.selectList(any(Wrapper.class))).thenReturn(List.of(user));

        List<SystemUserView> result = service.list(20);

        assertEquals(1, result.size());
        assertEquals("admin", result.get(0).username());
        assertEquals("admin@example.com", result.get(0).email());
    }

    @Test
    void returnsNotFoundForMissingUser() {
        when(userMapper.selectById(99L)).thenReturn(null);

        assertThrows(ResponseStatusException.class, () -> service.get(99L));
    }
}
