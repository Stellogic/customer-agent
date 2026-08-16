package com.stellogic.customeragent.identity;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest({AuthSessionController.class, DemoAccountController.class})
@Import({HumanSecurityConfiguration.class, ProductionHumanAccountsConfiguration.class})
@ActiveProfiles("production")
class ProductionHumanSessionSecurityTest {
    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;
    @Autowired private ApplicationContext context;

    @Test
    void productionHasNoLocalDemoAccountsOrCredentials() throws Exception {
        assertThat(context.getBeansOfType(DemoAccountController.class)).isEmpty();
        mvc.perform(get("/api/auth/demo-accounts")).andExpect(status().isNotFound());

        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession session = (MockHttpSession) csrf.getRequest().getSession(false);
        String token = json.readTree(csrf.getResponse().getContentAsString()).get("token").asText();

        mvc.perform(
                        post("/api/auth/login")
                                .session(session)
                                .header("X-CSRF-TOKEN", token)
                                .param("username", "customer-demo")
                                .param("password", "local-demo-password"))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/auth/session").session(session)).andExpect(status().isUnauthorized());
    }
}
