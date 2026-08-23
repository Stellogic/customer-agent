package com.stellogic.customeragent.compensation;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;

public final class DelayCompensationPolicy {
    public static final String VERSION = "delay-policy-v1";
    private static final BigDecimal TEN = new BigDecimal("10.00");
    private static final BigDecimal TWENTY = new BigDecimal("20.00");
    private static final BigDecimal REFUND_RATE = new BigDecimal("0.10");
    private static final BigDecimal REFUND_CAP = new BigDecimal("50.00");

    private static final Duration HOURS_24 = Duration.ofHours(24);
    private static final Duration HOURS_48 = Duration.ofHours(48);
    private static final Duration HOURS_72 = Duration.ofHours(72);

    public Decision evaluate(Duration delay, BigDecimal paidAmount) {
        if (delay.compareTo(HOURS_24) < 0) {
            return new Decision(false, Method.NONE, new BigDecimal("0.00"));
        }
        if (delay.compareTo(HOURS_48) < 0) {
            return new Decision(true, Method.COUPON, TEN);
        }
        if (delay.compareTo(HOURS_72) <= 0) {
            return new Decision(true, Method.COUPON, TWENTY);
        }
        BigDecimal amount =
                paidAmount.multiply(REFUND_RATE).min(REFUND_CAP).setScale(2, RoundingMode.HALF_UP);
        if (amount.signum() <= 0) {
            return new Decision(false, Method.NONE, new BigDecimal("0.00"));
        }
        return new Decision(true, Method.SIMULATED_PARTIAL_REFUND, amount);
    }

    public enum Method {
        NONE,
        COUPON,
        SIMULATED_PARTIAL_REFUND
    }

    public record Decision(boolean eligible, Method method, BigDecimal amount) {}
}
