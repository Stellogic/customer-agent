package com.stellogic.customeragent.status;

import java.util.LinkedHashMap;
import java.util.Map;

public final class SystemStatusService {
    private final AvailabilityProbe databaseProbe;
    private final AvailabilityProbe agentProbe;

    public SystemStatusService(AvailabilityProbe databaseProbe, AvailabilityProbe agentProbe) {
        this.databaseProbe = databaseProbe;
        this.agentProbe = agentProbe;
    }

    public SystemStatus current() {
        Map<String, String> services = new LinkedHashMap<>();
        services.put("spring", "UP");
        services.put("database", status(databaseProbe));
        services.put("agent", status(agentProbe));
        String overall = services.values().stream().allMatch("UP"::equals) ? "UP" : "DEGRADED";
        return new SystemStatus(overall, Map.copyOf(services));
    }

    private static String status(AvailabilityProbe probe) {
        try {
            return probe.isAvailable() ? "UP" : "DOWN";
        } catch (RuntimeException ignored) {
            return "DOWN";
        }
    }

    public record SystemStatus(String status, Map<String, String> services) {}
}

