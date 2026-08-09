package com.stellogic.customeragent.status;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class SystemStatusApiTest {

    @Test
    void browserReceivesOnlyTheMinimalSpringOwnedAvailabilityProjection() throws Exception {
        var service = new SystemStatusService(() -> true, () -> true);
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new SystemStatusController(service)).build();

        mvc.perform(get("/api/system/status"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.services.spring").value("UP"))
                .andExpect(jsonPath("$.services.database").value("UP"))
                .andExpect(jsonPath("$.services.agent").value("UP"))
                .andExpect(jsonPath("$.agentServerUrl").doesNotExist())
                .andExpect(jsonPath("$.credentials").doesNotExist());
    }
}
