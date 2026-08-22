package com.stellogic.customeragent.identity;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

public final class HumanSessionTestClient {
    private HumanSessionTestClient() {}

    public static MockHttpSession login(MockMvc mvc, ObjectMapper json, String username)
            throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymous = (MockHttpSession) csrf.getRequest().getSession(false);
        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(anonymous)
                                        .header("X-CSRF-TOKEN", token(json, csrf))
                                        .param("username", username)
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        return (MockHttpSession) login.getRequest().getSession(false);
    }

    public static String token(ObjectMapper json, MvcResult csrf) throws Exception {
        return json.readTree(csrf.getResponse().getContentAsString()).get("token").asText();
    }
}
