package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.identity.HumanIdentityDirectory;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanCapability;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanIdentity;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanRole;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.SubjectType;
import java.sql.Array;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class KnowledgeCatalogReadPathTest {
    @Test
    void ordinarySearchGoesThroughCatalogServiceAndExcludesNonCurrentVersions() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        stubReadyIndex(jdbc);
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        when(jdbc.query(
                        sql.capture(),
                        any(RowMapper.class),
                        any(),
                        any(),
                        any(),
                        any(),
                        any(),
                        any(),
                        any(),
                        any(),
                        anyInt()))
                .thenReturn(List.of());

        KnowledgeCatalogResponse response = service(jdbc).search("support-demo", "物流延迟", 20);

        assertThat(response.query()).isEqualTo("物流延迟");
        assertThat(sql.getValue()).contains("publication_status = 'PUBLISHED'");
        assertThat(sql.getValue()).contains("a.is_current");
        assertThat(sql.getValue()).contains("a.applicability &&");
        assertThat(sql.getValue()).doesNotContain("a.is_current = false");
    }

    @Test
    void articleVersionPathAuditsHistoricalVersionWithoutRequiringCurrent() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        stubReadyIndex(jdbc);
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ResultSet article = resultSet();
        when(jdbc.query(sql.capture(), any(RowMapper.class), any(), any(), any()))
                .thenAnswer(
                        invocation -> {
                            @SuppressWarnings("unchecked")
                            RowMapper<Object> mapper = invocation.getArgument(1);
                            return List.of(mapper.mapRow(article, 0));
                        });
        when(jdbc.query(contains("order by a.is_current"), any(RowMapper.class), any(), any()))
                .thenReturn(List.of());
        when(jdbc.query(contains("from knowledge_chunk"), any(RowMapper.class), any(), any()))
                .thenReturn(List.of());

        KnowledgeArticleResponse response =
                service(jdbc).article("support-demo", "logistics-delay", "v1");

        assertThat(response.article().articleId()).isEqualTo("logistics-delay");
        assertThat(response.article().version()).isEqualTo("v1");
        assertThat(response.article().current()).isFalse();
        assertThat(sql.getAllValues().getFirst()).contains("a.version = ?");
        assertThat(sql.getAllValues().getFirst()).doesNotContain("a.is_current");
    }

    private static JdbcKnowledgeCatalogService service(JdbcTemplate jdbc) {
        return new JdbcKnowledgeCatalogService(
                jdbc,
                new KnowledgeAccessPolicy(
                        new HumanIdentityDirectory(
                                List.of(
                                        new HumanIdentity(
                                                "support-demo",
                                                "演示客服",
                                                SubjectType.INTERNAL,
                                                List.of(HumanRole.SUPPORT),
                                                List.of(
                                                        HumanCapability.SUPPORT_WORKBENCH_ACCESS,
                                                        HumanCapability.KNOWLEDGE_READ_ACCESS))))));
    }

    private static void stubReadyIndex(JdbcTemplate jdbc) {
        when(jdbc.queryForObject(anyString(), any(RowMapper.class)))
                .thenReturn(
                        new KnowledgeIndexState(
                                KnowledgeIndexStatus.READY,
                                2,
                                "a".repeat(64),
                                Instant.parse("2026-08-28T00:00:00Z"),
                                Instant.parse("2026-08-28T00:00:00Z"),
                                2,
                                3,
                                null,
                                null));
    }

    private static ResultSet resultSet() throws Exception {
        ResultSet rs = mock(ResultSet.class);
        Array applicability = mock(Array.class);
        when(applicability.getArray()).thenReturn(new String[] {"INTERNAL", "SUPPORT"});
        when(rs.getString(1)).thenReturn("logistics-delay");
        when(rs.getString(2)).thenReturn("物流延迟处理说明");
        when(rs.getString(3)).thenReturn("v1");
        when(rs.getTimestamp(4)).thenReturn(Timestamp.from(Instant.parse("2026-08-20T00:00:00Z")));
        when(rs.getArray(5)).thenReturn(applicability);
        when(rs.getString(6)).thenReturn("RETIRED");
        when(rs.getBoolean(7)).thenReturn(false);
        when(rs.getString(8)).thenReturn("knowledge/logistics-delay-v1.md");
        when(rs.getString(9)).thenReturn("c".repeat(64));
        when(rs.getString(10)).thenReturn("旧版本规则只用于审计历史回复。");
        return rs;
    }
}
