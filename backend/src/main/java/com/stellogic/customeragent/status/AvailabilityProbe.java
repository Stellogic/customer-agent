package com.stellogic.customeragent.status;

@FunctionalInterface
public interface AvailabilityProbe {
    boolean isAvailable();
}

