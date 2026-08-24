package com.bdlh.runtime.mapper;

import com.baomidou.dynamic.datasource.annotation.DS;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.bdlh.runtime.entity.User;

/**
 * 用户表的数据访问层，走 MySQL 数据源（系统模块）。
 */
@DS("mysql")
public interface UserMapper extends BaseMapper<User> {
}
