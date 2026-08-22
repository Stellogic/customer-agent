package com.stellogic.customeragent;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.lang.ArchRule;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.RestController;

final class ArchitectureTest {
    private final JavaClasses productionClasses =
            new ClassFileImporter().importPackages("com.stellogic.customeragent");

    @Test
    void controllersDependOnPortsRatherThanJdbcImplementations() {
        ArchRule rule =
                noClasses()
                        .that()
                        .areAnnotatedWith(RestController.class)
                        .should()
                        .dependOnClassesThat()
                        .haveSimpleNameStartingWith("Jdbc");

        rule.check(productionClasses);
    }

    @Test
    void compensationPolicyRemainsIndependentOfSpring() {
        ArchRule rule =
                noClasses()
                        .that()
                        .resideInAnyPackage("..compensation..")
                        .should()
                        .dependOnClassesThat()
                        .resideInAnyPackage("org.springframework..");

        rule.check(productionClasses);
    }

    @Test
    void legacySyntheticHumanIdentityEntrypointsAreAbsent() {
        ArchRule rule =
                noClasses()
                        .should()
                        .haveSimpleName("SyntheticIdentityController")
                        .orShould()
                        .haveSimpleName("SyntheticApprovers");

        rule.check(productionClasses);
    }
}
