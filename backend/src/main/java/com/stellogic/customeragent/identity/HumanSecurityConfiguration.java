package com.stellogic.customeragent.identity;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import org.springframework.boot.web.servlet.ServletListenerRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration(proxyBeanMethods = false)
@EnableWebSecurity
public class HumanSecurityConfiguration {
    @Bean
    PasswordEncoder humanPasswordEncoder() {
        return PasswordEncoderFactories.createDelegatingPasswordEncoder();
    }

    @Bean
    HumanSecurityEvents humanSecurityEvents() {
        return new HumanSecurityEvents();
    }

    @Bean
    ServletListenerRegistrationBean<HumanSessionExpirationListener> humanSessionExpirationListener(
            HumanSecurityEvents securityEvents) {
        return new ServletListenerRegistrationBean<>(
                new HumanSessionExpirationListener(securityEvents));
    }

    @Bean
    SecurityFilterChain humanSessionSecurity(HttpSecurity http, HumanSecurityEvents securityEvents)
            throws Exception {
        http.securityMatcher(
                        "/api/auth/**", "/api/customer/**", "/api/support/**", "/api/approver/**")
                .authorizeHttpRequests(
                        requests ->
                                requests.requestMatchers(
                                                "/api/auth/csrf",
                                                "/api/auth/login",
                                                "/api/auth/demo-accounts")
                                        .permitAll()
                                        .requestMatchers("/api/customer/**")
                                        .hasRole("CUSTOMER")
                                        .requestMatchers("/api/support/**")
                                        .hasRole("SUPPORT")
                                        .requestMatchers("/api/approver/**")
                                        .hasRole("APPROVER")
                                        .anyRequest()
                                        .authenticated())
                .formLogin(
                        form ->
                                form.loginProcessingUrl("/api/auth/login")
                                        .successHandler(
                                                (request, response, authentication) -> {
                                                    Object previousSessionId =
                                                            request.getAttribute(
                                                                    HumanLoginSseRevocationFilter
                                                                            .PREVIOUS_SESSION_ID_ATTRIBUTE);
                                                    if (previousSessionId instanceof String id) {
                                                        AuthorizedSsePollingStream
                                                                .invalidateHttpSessionId(id);
                                                    }
                                                    var session = request.getSession(false);
                                                    if (session != null) {
                                                        AuthorizedSsePollingStream
                                                                .rotateHttpSession(session);
                                                    }
                                                    securityEvents.loginSucceeded(
                                                            authentication.getName());
                                                    response.setStatus(
                                                            HttpStatus.NO_CONTENT.value());
                                                })
                                        .failureHandler(
                                                (request, response, exception) -> {
                                                    securityEvents.loginFailed();
                                                    response.sendError(
                                                            HttpStatus.UNAUTHORIZED.value());
                                                }))
                .logout(
                        logout ->
                                logout.logoutUrl("/api/auth/logout")
                                        .addLogoutHandler(
                                                (request, response, authentication) -> {
                                                    var session = request.getSession(false);
                                                    if (session != null) {
                                                        AuthorizedSsePollingStream
                                                                .invalidateHttpSession(session);
                                                        session.setAttribute(
                                                                HumanSecurityEvents
                                                                        .EXPLICIT_LOGOUT_ATTRIBUTE,
                                                                Boolean.TRUE);
                                                    }
                                                })
                                        .logoutSuccessHandler(
                                                (request, response, authentication) -> {
                                                    if (authentication != null) {
                                                        securityEvents.loggedOut(
                                                                authentication.getName());
                                                    }
                                                    response.setStatus(
                                                            HttpStatus.NO_CONTENT.value());
                                                }))
                .exceptionHandling(
                        exceptions ->
                                exceptions.authenticationEntryPoint(
                                        new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED)))
                .requestCache(cache -> cache.disable())
                .sessionManagement(
                        sessions ->
                                sessions.sessionFixation(fixation -> fixation.changeSessionId()));
        http.addFilterBefore(
                new HumanLoginSseRevocationFilter(), UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
