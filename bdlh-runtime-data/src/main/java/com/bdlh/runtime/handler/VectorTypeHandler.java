package com.bdlh.runtime.handler;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;
import org.postgresql.util.PGobject;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/**
 * pgvector 向量列与 Java float[] 的双向转换器。
 * 写入时用 PGobject 标注类型为 vector，绕开 PG 对 text→vector 的隐式转换限制。
 */
public class VectorTypeHandler extends BaseTypeHandler<float[]> {

    /**
     * 将 float[] 拼成 pgvector 文本格式并用 PGobject 写入，确保 PG 识别为 vector 类型。
     */
    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, float[] parameter, JdbcType jdbcType) throws SQLException {
        // 1. 拼接成 [v1,v2,...] 形式的向量文本
        StringBuilder sb = new StringBuilder("[");
        for (int j = 0; j < parameter.length; j++) {
            if (j > 0) {
                sb.append(',');
            }
            sb.append(parameter[j]);
        }
        sb.append(']');
        // 2. 用 PGobject 显式声明 vector 类型，避免被当作 text 导致类型不匹配
        PGobject pgo = new PGobject();
        pgo.setType("vector");
        pgo.setValue(sb.toString());
        ps.setObject(i, pgo);
    }

    @Override
    public float[] getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return parse(rs.getString(columnName));
    }

    @Override
    public float[] getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return parse(rs.getString(columnIndex));
    }

    @Override
    public float[] getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return parse(cs.getString(columnIndex));
    }

    /**
     * 把数据库返回的 "[v1,v2,...]" 文本解析回 float[]。
     */
    private float[] parse(String s) {
        // 1. 空值保护
        if (s == null || s.isBlank()) {
            return null;
        }
        // 2. 去掉方括号后按逗号切分
        String inner = s.replace("[", "").replace("]", "").trim();
        if (inner.isEmpty()) {
            return new float[0];
        }
        String[] parts = inner.split(",");
        // 3. 逐段解析为浮点
        float[] arr = new float[parts.length];
        for (int i = 0; i < parts.length; i++) {
            arr[i] = Float.parseFloat(parts[i].trim());
        }
        return arr;
    }
}
