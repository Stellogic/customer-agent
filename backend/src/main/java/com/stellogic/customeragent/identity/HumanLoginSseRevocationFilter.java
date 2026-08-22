package com.stellogic.customeragent.identity;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.web.filter.OncePerRequestFilter;

final class HumanLoginSseRevocationFilter extends OncePerRequestFilter {
    static final String PREVIOUS_SESSION_ID_ATTRIBUTE =
            HumanLoginSseRevocationFilter.class.getName() + ".previousSessionId";

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !"POST".equals(request.getMethod())
                || !"/api/auth/login".equals(request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        var previousSession = request.getSession(false);
        if (previousSession != null) {
            request.setAttribute(PREVIOUS_SESSION_ID_ATTRIBUTE, previousSession.getId());
        }
        filterChain.doFilter(request, response);
    }
}
