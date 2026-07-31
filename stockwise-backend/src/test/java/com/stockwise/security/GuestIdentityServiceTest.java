package com.stockwise.security;

import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证游客身份只以随机Cookie存在于浏览器，业务层获得稳定哈希。
 */
class GuestIdentityServiceTest {

    private final GuestIdentityService service = new GuestIdentityService();

    @Test
    void shouldIssueSecureCookieAndReturnHash() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Forwarded-Proto", "https");
        MockHttpServletResponse response = new MockHttpServletResponse();

        String subjectHash = service.resolveSubjectHash(request, response);

        assertThat(subjectHash).matches("[a-f0-9]{64}");
        assertThat(response.getHeader(HttpHeaders.SET_COOKIE))
                .contains(GuestIdentityService.COOKIE_NAME + "=")
                .contains("HttpOnly")
                .contains("SameSite=Lax")
                .contains("Secure");
    }

    @Test
    void shouldReuseExistingGuestCookie() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setCookies(new Cookie(
                GuestIdentityService.COOKIE_NAME,
                "0123456789abcdef0123456789abcdef"));
        MockHttpServletResponse firstResponse = new MockHttpServletResponse();
        MockHttpServletResponse secondResponse = new MockHttpServletResponse();

        String first = service.resolveSubjectHash(request, firstResponse);
        String second = service.resolveSubjectHash(request, secondResponse);

        assertThat(first).isEqualTo(second);
        assertThat(firstResponse.getHeader(HttpHeaders.SET_COOKIE)).isNull();
        assertThat(secondResponse.getHeader(HttpHeaders.SET_COOKIE)).isNull();
    }
}
