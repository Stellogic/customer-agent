package com.stellogic.customeragent.identity;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;

@Configuration(proxyBeanMethods = false)
@EnableWebSecurity
public class HumanSecurityConfiguration {
    @Bean
    PasswordEncoder humanPasswordEncoder() {
        return PasswordEncoderFactories.createDelegatingPasswordEncoder();
    }

    @Bean
    SecurityFilterChain humanSessionSecurity(HttpSecurity http) throws Exception {
        http.securityMatcher("/api/auth/**", "/api/customer/**")
                .authorizeHttpRequests(
                        requests ->
                                requests.requestMatchers(
                                                "/api/auth/csrf",
                                                "/api/auth/login",
                                                "/api/auth/demo-accounts")
                                        .permitAll()
                                        .requestMatchers("/api/customer/**")
                                        .hasRole("CUSTOMER")
                                        .anyRequest()
                                        .authenticated())
                .formLogin(
                        form ->
                                form.loginProcessingUrl("/api/auth/login")
                                        .successHandler(
                                                (request, response, authentication) ->
                                                        response.setStatus(
                                                                HttpStatus.NO_CONTENT.value()))
                                        .failureHandler(
                                                (request, response, exception) ->
                                                        response.sendError(
                                                                HttpStatus.UNAUTHORIZED.value())))
                .logout(
                        logout ->
                                logout.logoutUrl("/api/auth/logout")
                                        .logoutSuccessHandler(
                                                (request, response, authentication) ->
                                                        response.setStatus(
                                                                HttpStatus.NO_CONTENT.value())))
                .exceptionHandling(
                        exceptions ->
                                exceptions.authenticationEntryPoint(
                                        new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED)))
                .requestCache(cache -> cache.disable())
                .sessionManagement(
                        sessions ->
                                sessions.sessionFixation(fixation -> fixation.changeSessionId()));
        return http.build();
    }
}
