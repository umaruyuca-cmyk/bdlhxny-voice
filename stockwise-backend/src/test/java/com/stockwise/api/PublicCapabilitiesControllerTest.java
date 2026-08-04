package com.stockwise.api;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证公开能力目录接口只返回脱敏信息，不泄露密钥、IP 或内部地址。
 */
class PublicCapabilitiesControllerTest {

    private final PublicCapabilitiesController controller = new PublicCapabilitiesController();

    @Test
    void shouldReturnBothAgents() {
        Map<String, Object> body = controller.capabilities();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> agents = (List<Map<String, Object>>) body.get("agents");
        assertThat(agents).hasSize(2);
        assertThat(agents).extracting("id").containsExactly("general", "stock");
        assertThat(agents).allMatch(a -> "available".equals(a.get("status")));
    }

    @Test
    void shouldReturnFourSkillsWithDocsPath() {
        Map<String, Object> body = controller.capabilities();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> skills = (List<Map<String, Object>>) body.get("skills");
        assertThat(skills).hasSize(4);
        assertThat(skills).extracting("id").containsExactly("stock", "portfolio", "quant", "sector");
        assertThat(skills).allMatch(s -> "/docs/skill".equals(s.get("docsPath")));
    }

    @Test
    void shouldNotExposeSecretsOrInternalAddresses() {
        String serialized = controller.capabilities().toString();
        assertThat(serialized).doesNotContain("token", "secret", "password", "api-key");
        assertThat(serialized).doesNotContain("118.", "http://", "jdbc:", "10.", "172.");
    }
}
