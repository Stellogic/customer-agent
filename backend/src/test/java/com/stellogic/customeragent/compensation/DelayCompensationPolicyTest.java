package com.stellogic.customeragent.compensation;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class DelayCompensationPolicyTest {
    private final DelayCompensationPolicy policy = new DelayCompensationPolicy();

    @ParameterizedTest
    @MethodSource("tiers")
    void policyTiersAreMutuallyExclusiveAtEveryBoundary(
            Duration delay,
            boolean eligible,
            DelayCompensationPolicy.Method method,
            String amount) {
        DelayCompensationPolicy.Decision decision =
                policy.evaluate(delay, new BigDecimal("268.00"));

        assertThat(decision.eligible()).isEqualTo(eligible);
        assertThat(decision.method()).isEqualTo(method);
        assertThat(decision.amount()).isEqualByComparingTo(amount);
    }

    static Stream<Arguments> tiers() {
        return Stream.of(
                Arguments.of(
                        Duration.ofHours(24).minusNanos(1),
                        false,
                        DelayCompensationPolicy.Method.NONE,
                        "0.00"),
                Arguments.of(
                        Duration.ofHours(24), true, DelayCompensationPolicy.Method.COUPON, "10.00"),
                Arguments.of(
                        Duration.ofHours(24).plusNanos(1),
                        true,
                        DelayCompensationPolicy.Method.COUPON,
                        "10.00"),
                Arguments.of(
                        Duration.ofHours(48).minusNanos(1),
                        true,
                        DelayCompensationPolicy.Method.COUPON,
                        "10.00"),
                Arguments.of(
                        Duration.ofHours(48), true, DelayCompensationPolicy.Method.COUPON, "20.00"),
                Arguments.of(
                        Duration.ofHours(48).plusNanos(1),
                        true,
                        DelayCompensationPolicy.Method.COUPON,
                        "20.00"),
                Arguments.of(
                        Duration.ofHours(72).minusNanos(1),
                        true,
                        DelayCompensationPolicy.Method.COUPON,
                        "20.00"),
                Arguments.of(
                        Duration.ofHours(72), true, DelayCompensationPolicy.Method.COUPON, "20.00"),
                Arguments.of(
                        Duration.ofHours(72).plusNanos(1),
                        true,
                        DelayCompensationPolicy.Method.SIMULATED_PARTIAL_REFUND,
                        "26.80"));
    }

    @Test
    void partialRefundUsesDecimalHalfUpCentsAndFiftyCnyCap() {
        assertThat(policy.evaluate(Duration.ofHours(80), new BigDecimal("268.05")).amount())
                .isEqualByComparingTo("26.81");
        assertThat(policy.evaluate(Duration.ofHours(80), new BigDecimal("999.99")).amount())
                .isEqualByComparingTo("50.00");
    }
}
