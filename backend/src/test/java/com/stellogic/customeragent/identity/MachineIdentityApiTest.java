package com.stellogic.customeragent.identity;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class MachineIdentityApiTest {
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(
                    new MachineIdentityController("agent-secret", "executor-secret"))
            .build();

    @Test
    void agentAndExecutorCannotUseEachOthersCapability() throws Exception {
        mvc.perform(get("/internal/capabilities/agent/probe")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer agent-secret"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.identity").value("agent"));

        mvc.perform(get("/internal/capabilities/executor/probe")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer agent-secret"))
                .andExpect(status().isForbidden());

        mvc.perform(get("/internal/capabilities/agent/probe")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret"))
                .andExpect(status().isForbidden());
    }
}
