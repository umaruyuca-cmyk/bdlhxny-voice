package com.bdlh.runtime.handler;

import org.apache.ibatis.type.TypeHandler;
import org.apache.ibatis.type.TypeHandlerRegistry;
import org.junit.jupiter.api.Test;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证 UUID TypeHandler 的全局注册元数据、JDBC 写入和多种读取结果兼容性。
 */
class UuidTypeHandlerTest {

    private final UuidTypeHandler handler = new UuidTypeHandler();

    @Test
    void registersForUuidWithoutExplicitJdbcType() {
        TypeHandlerRegistry registry = new TypeHandlerRegistry();

        registry.register("com.bdlh.runtime.handler");

        TypeHandler<UUID> registered = registry.getTypeHandler(UUID.class);
        assertInstanceOf(UuidTypeHandler.class, registered);
    }

    @Test
    void jsonbHandlerDoesNotCaptureGenericObjectParameters() {
        TypeHandlerRegistry registry = new TypeHandlerRegistry();

        registry.register("com.bdlh.runtime.handler");

        TypeHandler<Object> registered = registry.getTypeHandler(Object.class);
        assertInstanceOf(org.apache.ibatis.type.UnknownTypeHandler.class, registered);
    }

    @Test
    void writesUuidAsNativeJdbcObject() throws SQLException {
        PreparedStatement statement = mock(PreparedStatement.class);
        UUID value = UUID.randomUUID();

        handler.setNonNullParameter(statement, 2, value, null);

        verify(statement).setObject(2, value);
    }

    @Test
    void readsUuidAndStringValues() throws SQLException {
        ResultSet resultSet = mock(ResultSet.class);
        CallableStatement callableStatement = mock(CallableStatement.class);
        UUID value = UUID.randomUUID();
        when(resultSet.getObject("run_id")).thenReturn(value);
        when(resultSet.getObject(3)).thenReturn(value.toString());
        when(callableStatement.getObject(4)).thenReturn(null);

        assertEquals(value, handler.getNullableResult(resultSet, "run_id"));
        assertEquals(value, handler.getNullableResult(resultSet, 3));
        assertNull(handler.getNullableResult(callableStatement, 4));
    }

    @Test
    void rejectsInvalidUuidText() throws SQLException {
        ResultSet resultSet = mock(ResultSet.class);
        when(resultSet.getObject("run_id")).thenReturn("not-a-uuid");

        assertThrows(SQLException.class, () -> handler.getNullableResult(resultSet, "run_id"));
    }
}
