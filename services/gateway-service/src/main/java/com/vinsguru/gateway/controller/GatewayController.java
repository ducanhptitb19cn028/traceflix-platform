package com.vinsguru.gateway.controller;

import com.vinsguru.gateway.dto.HomePageDto;
import com.vinsguru.gateway.service.GatewayService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class GatewayController {

    private static final Logger log = LoggerFactory.getLogger(GatewayController.class);

    private final GatewayService gatewayService;

    public GatewayController(GatewayService gatewayService) {
        this.gatewayService = gatewayService;
    }

    @GetMapping("/api/browse")
    public HomePageDto browse(@RequestParam(defaultValue = "1") Integer userId) {
        log.info("home page requested for user {}", userId);
        return this.gatewayService.browse(userId);
    }

}
