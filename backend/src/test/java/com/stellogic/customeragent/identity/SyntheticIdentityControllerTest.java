package com.stellogic.customeragent.identity;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class SyntheticIdentityControllerTest {
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new SyntheticIdentityController()).build();

    @Test
    void supportDemoEntryCreatesAnHttpOnlySessionBeforeRedirectingToTheRegisteredRoute() throws Exception {
        mvc.perform(get("/api/demo/enter/support"))
                .andExpect(status().isFound())
                .andExpect(redirectedUrl("/support"))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.allOf(
                        org.hamcrest.Matchers.containsString("synthetic-demo-session=support-demo"),
                        org.hamcrest.Matchers.containsString("HttpOnly"),
                        org.hamcrest.Matchers.containsString("SameSite=Strict"))));
    }

    @Test
    void directRouteHasNoSupportSessionButTheIssuedCookieRegistersSupport() throws Exception {
        mvc.perform(get("/api/demo/session"))
                .andExpect(status().isUnauthorized());

        mvc.perform(get("/api/demo/session")
                        .cookie(new jakarta.servlet.http.Cookie("synthetic-demo-session", "support-demo")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("support-demo"))
                .andExpect(jsonPath("$.role").value("SUPPORT"));
    }
}
