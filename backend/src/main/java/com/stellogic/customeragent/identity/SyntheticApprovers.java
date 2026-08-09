package com.stellogic.customeragent.identity;

import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

public final class SyntheticApprovers {
    private static final List<Entry> ENTRIES = List.of(
            new Entry("approver-demo", "审批人演示入口"),
            new Entry("approver-other-demo", "另一审批人并发边界入口"));
    private static final Set<String> IDS = ENTRIES.stream()
            .map(Entry::id)
            .collect(Collectors.toUnmodifiableSet());

    private SyntheticApprovers() {}

    public static boolean contains(String id) {
        return IDS.contains(id);
    }

    public static List<Entry> entries() {
        return ENTRIES;
    }

    public record Entry(String id, String label) {}
}
