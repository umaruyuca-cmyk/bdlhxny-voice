package com.stockwise.handler;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;
import org.apache.ibatis.type.MappedTypes;
import org.postgresql.util.PGobject;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;

/**
 * PostgreSQL JSONB 列与 Java 对象的双向转换器。
 * 用 PGobject 声明 jsonb 类型，读侧用 Jackson 反序列化为 Map/List，统一承载动态结构。
 */
@MappedTypes({Map.class, List.class})
public class JsonbTypeHandler extends BaseTypeHandler<Object> {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * 序列化为 JSON 文本并以 jsonb 类型写入；入参已是字符串则直接使用，避免二次转义。
     */
    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, Object parameter, JdbcType jdbcType) throws SQLException {
        try {
            // 1. 字符串直接用，对象则交给 Jackson 序列化
            String json = (parameter instanceof String s) ? s : MAPPER.writeValueAsString(parameter);
            // 2. 声明 jsonb 类型写入
            PGobject pgo = new PGobject();
            pgo.setType("jsonb");
            pgo.setValue(json);
            ps.setObject(i, pgo);
        } catch (Exception e) {
            throw new SQLException("Failed to serialize JSONB", e);
        }
    }

    @Override
    public Object getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return parse(rs.getString(columnName));
    }

    @Override
    public Object getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return parse(rs.getString(columnIndex));
    }

    @Override
    public Object getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return parse(cs.getString(columnIndex));
    }

    /**
     * 将 JSONB 文本反序列化为对象；解析失败返回 null 而非抛异常，避免单条脏数据拖垮整次查询。
     */
    private Object parse(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        try {
            return MAPPER.readValue(s, Object.class);
        } catch (Exception e) {
            return null;
        }
    }
}
